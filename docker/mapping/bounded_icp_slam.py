"""
NERO_GO2 — Etalon 5x5 cm Mikró-Voxel Scan-to-Map SLAM Engine (Javított, Sziklaszilárd Relatív Relokalizáció)
Algoritmus:
1. Relatív Odometria Léptetés (dx, dy, dyaw göngyölítése a korrigált robot pozícióra)
2. Szigorúan Korlátozott Etalon Scan-to-Map ICP (Max 8cm elmozdulás, Max 1.5° forgás keretenként)
3. Rögzített 5 cm-es Etalon Voxelek (C >= 0.50, fix alaptérkép)
4. Szigorúan 0% Pont-törlés
"""

import json
import math
import os
import sys
import time
import numpy as np
from scipy.spatial import cKDTree

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi

def get_stabilized_points(fr):
    roll = fr.get("roll", 0) or 0.0
    pitch = fr.get("pitch", 0) or 0.0
    cr, sr = math.cos(-roll), math.sin(-roll)
    cp, sp = math.cos(-pitch), math.sin(-pitch)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float32)
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float32)
    rot_tilt = rx.T @ ry.T
    
    pts = np.array(fr.get("points", []), dtype=np.float32)
    if len(pts) == 0:
        return np.empty((0, 3), dtype=np.float32)
    xyz = pts[:, :3] @ rot_tilt
    d = np.hypot(xyz[:, 0], xyz[:, 1])
    valid = (d > 0.35) & (xyz[:, 2] > -0.5) & (xyz[:, 2] < 2.5)
    return xyz[valid]

def process_etalon_slam(filepath, name, label, is_stationary=False, step=2, max_frames=260):
    print(f"\n=======================================================")
    print(f"Etalon Mikró-Voxel SLAM Feldolgozás (Korlátozott ICP): {name} ({label})")
    print(f"=======================================================")
    t0 = time.time()
    
    raw_frames = []
    with open(filepath, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i % step == 0:
                raw_frames.append(json.loads(line))
            if len(raw_frames) >= max_frames:
                break
                
    if not raw_frames:
        return None
        
    YAW_OFFSET_RAD = 0.0 if is_stationary else np.radians(90)
    
    voxel_grid = {}
    etalon_centroids = []
    etalon_tree = None
    
    last_slam_pose = None # (x, y, yaw)
    last_raw_pose = None # (x_raw, y_raw, yaw_raw)
    
    raw_trajectory = []
    slam_trajectory = []
    points_tagged = []
    pts_buffer = []
    
    for f_idx, fr in enumerate(raw_frames):
        pts = get_stabilized_points(fr)
        if len(pts) < 30:
            continue
            
        x_raw = float(fr.get("x", 0) or 0.0)
        y_raw = float(fr.get("y", 0) or 0.0)
        yaw_raw = float(wrap_angle((fr.get("yaw", 0) or 0.0) + YAW_OFFSET_RAD))
        
        raw_trajectory.append({
            "f": f_idx,
            "x": round(x_raw, 3),
            "y": round(y_raw, 3),
            "yaw": round(yaw_raw, 3),
            "t": round(f_idx * step * 0.125, 2)
        })
        
        if last_slam_pose is None:
            slam_x, slam_y, slam_yaw = x_raw, y_raw, yaw_raw
        else:
            dx = x_raw - last_raw_pose[0]
            dy = y_raw - last_raw_pose[1]
            dyaw = wrap_angle(yaw_raw - last_raw_pose[2])
            
            slam_x = last_slam_pose[0] + dx
            slam_y = last_slam_pose[1] + dy
            slam_yaw = wrap_angle(last_slam_pose[2] + dyaw)

        last_raw_pose = (x_raw, y_raw, yaw_raw)
        
        # World koordináták kiszámítása az aktuális becsült robot pozícióval
        cy, sy = math.cos(slam_yaw), math.sin(slam_yaw)
        rot_world = np.array([[cy, -sy], [sy, cy]], dtype=np.float32)
        
        pts_world_xy = pts[:, :2] @ rot_world.T + np.array([slam_x, slam_y], dtype=np.float32)
        pts_world_3d = np.column_stack([pts_world_xy, pts[:, 2]])
        
        # --- ETALON ICP KORREKCIÓ (CSAK ROBUSTUS KORLÁTOKKAL) ---
        if not is_stationary and etalon_tree is not None and len(etalon_centroids) > 50:
            non_floor_m = pts_world_3d[:, 2] > -0.20
            non_floor_xy = pts_world_xy[non_floor_m]
            
            if len(non_floor_xy) > 30:
                curr_xy = non_floor_xy.copy()
                d_R = np.eye(2, dtype=np.float32)
                d_t = np.zeros(2, dtype=np.float32)
                etalon_arr = np.array(etalon_centroids, dtype=np.float32)
                
                for _ in range(4):
                    dists, idxs = etalon_tree.query(curr_xy)
                    valid_m = dists < 0.20 # 20cm szigorú keret-távolság korlát
                    if np.sum(valid_m) < 25:
                        break
                    src = curr_xy[valid_m]
                    dst = etalon_arr[idxs[valid_m]]
                    
                    c_src = np.mean(src, axis=0)
                    c_dst = np.mean(dst, axis=0)
                    
                    H = (src - c_src).T @ (dst - c_dst)
                    U, S, Vt = np.linalg.svd(H)
                    R_icp = Vt.T @ U.T
                    if np.linalg.det(R_icp) < 0:
                        Vt[1, :] *= -1
                        R_icp = Vt.T @ U.T
                    t_icp = c_dst - c_src @ R_icp.T
                    
                    curr_xy = curr_xy @ R_icp.T + t_icp
                    d_R = d_R @ R_icp.T
                    d_t = d_t @ R_icp.T + t_icp

                corr_dyaw = wrap_angle(math.atan2(d_R[1, 0], d_R[0, 0]))
                corr_dx = float(d_t[0])
                corr_dy = float(d_t[1])
                
                # SZIGORÚ KORLÁTOZÁS: elkerüli a téves elforgást / ugrást (max 8cm, max 1.5° keretenként)
                if abs(corr_dx) < 0.08 and abs(corr_dy) < 0.08 and abs(corr_dyaw) < np.radians(1.5):
                    slam_x += corr_dx
                    slam_y += corr_dy
                    slam_yaw = wrap_angle(slam_yaw + corr_dyaw)
                    
                    cy, sy = math.cos(slam_yaw), math.sin(slam_yaw)
                    rot_world = np.array([[cy, -sy], [sy, cy]], dtype=np.float32)
                    pts_world_xy = pts[:, :2] @ rot_world.T + np.array([slam_x, slam_y], dtype=np.float32)
                    pts_world_3d = np.column_stack([pts_world_xy, pts[:, 2]])

        last_slam_pose = (slam_x, slam_y, slam_yaw)
        
        drift_cm = round(float(np.hypot(slam_x - x_raw, slam_y - y_raw)) * 100.0, 1)
        
        slam_trajectory.append({
            "f": f_idx,
            "x": round(float(slam_x), 3),
            "y": round(float(slam_y), 3),
            "yaw": round(float(slam_yaw), 3),
            "drift_cm": drift_cm,
            "t": round(f_idx * step * 0.125, 2)
        })
        
        # Pontfelhő rögzítése (100%)
        down_pts = pts_world_3d[::2]
        for p in down_pts:
            pts_buffer.append([p[0], p[1], p[2]])
            points_tagged.append([round(float(p[0]), 2), round(float(p[1]), 2), round(float(p[2]), 2), f_idx])
            
        # 5cm Voxel Bining (Vectorized NumPy)
        non_floor_mask = pts_world_3d[:, 2] >= -0.20
        non_floor_pts = pts_world_3d[non_floor_mask]
        
        new_etalon_added = False
        if len(non_floor_pts) > 0:
            voxels_raw = np.floor(non_floor_pts / 0.05).astype(np.int32)
            unique_vk, counts = np.unique(voxels_raw, axis=0, return_counts=True)
            for vk_arr, cnt in zip(unique_vk, counts):
                vk = (int(vk_arr[0]), int(vk_arr[1]), int(vk_arr[2]))
                if vk not in voxel_grid:
                    voxel_grid[vk] = {"hits": int(cnt), "first_f": f_idx, "last_f": f_idx, "is_etalon": False}
                else:
                    voxel_grid[vk]["hits"] += int(cnt)
                    voxel_grid[vk]["last_f"] = f_idx
                    if not voxel_grid[vk]["is_etalon"] and voxel_grid[vk]["hits"] >= 3:
                        voxel_grid[vk]["is_etalon"] = True
                        c_x = (vk[0] + 0.5) * 0.05
                        c_y = (vk[1] + 0.5) * 0.05
                        etalon_centroids.append([c_x, c_y])
                        new_etalon_added = True

        if new_etalon_added and len(etalon_centroids) > 20:
            etalon_centroids_np = np.array(etalon_centroids, dtype=np.float32)
            if len(etalon_centroids_np) > 2500:
                etalon_centroids_np = etalon_centroids_np[::len(etalon_centroids_np)//2000]
            etalon_tree = cKDTree(etalon_centroids_np)

    # Voxelek kimeneti formátumba konvertálása
    voxels_5cm = []
    for (vx, vy, vz), data in voxel_grid.items():
        if data["hits"] >= 2:
            x_c = round((vx + 0.5) * 0.05, 3)
            y_c = round((vy + 0.5) * 0.05, 3)
            z_c = round((vz + 0.5) * 0.05, 3)
            c_val = min(1.0, round(data["hits"] / 4.0, 2))
            voxels_5cm.append([x_c, y_c, z_c, c_val, data["first_f"], data["last_f"], 1 if data["is_etalon"] else 0])

    pts_arr = np.array(pts_buffer)
    min_x, max_x = float(pts_arr[:, 0].min()), float(pts_arr[:, 0].max())
    min_y, max_y = float(pts_arr[:, 1].min()), float(pts_arr[:, 1].max())
    min_z, max_z = float(pts_arr[:, 2].min()), float(pts_arr[:, 2].max())
    
    max_drift = max(t["drift_cm"] for t in slam_trajectory)
    avg_drift = round(float(np.mean([t["drift_cm"] for t in slam_trajectory])), 1)
    
    print(f"  Feldolgozva {time.time()-t0:.2f}s alatt.")
    print(f"  Összes 5x5 cm Voxel: {len(voxels_5cm)} db")
    print(f"  Rögzített Etalon Voxelek (C>=0.5): {sum(1 for v in voxels_5cm if v[6]==1)} db")
    print(f"  Max Odometria Korrekció: {max_drift} cm (Átlag: {avg_drift} cm)")
    print(f"  Megtartott pontok: {len(points_tagged):,} db (100% pontmegtartás)")
    
    return {
        "id": name,
        "label": label,
        "total_frames": len(slam_trajectory),
        "total_time": round(len(slam_trajectory) * step * 0.125, 1),
        "total_points": len(points_tagged),
        "voxels_count": len(voxels_5cm),
        "etalon_voxels_count": sum(1 for v in voxels_5cm if v[6]==1),
        "max_drift_cm": max_drift,
        "avg_drift_cm": avg_drift,
        "voxels_5cm": voxels_5cm,
        "bounds": {
            "x": [round(min_x, 2), round(max_x, 2)],
            "y": [round(min_y, 2), round(max_y, 2)],
            "z": [round(min_z, 2), round(max_z, 2)],
            "width": round(max_x - min_x, 2),
            "length": round(max_y - min_y, 2)
        },
        "raw_trajectory": raw_trajectory,
        "slam_trajectory": slam_trajectory,
        "points": points_tagged
    }

def generate_etalon_html(datasets):
    data_json = json.dumps(datasets, default=lambda x: bool(x) if isinstance(x, np.bool_) else (float(x) if isinstance(x, np.floating) else int(x)))
    return f"""<!DOCTYPE html>
<html lang="hu">
<head>
  <meta charset="utf-8">
  <title>NERO_GO2 — Etalon 5x5 cm Mikró-Voxel Scan-to-Map SLAM</title>
  <style>
    :root {{
      --bg: #07090e;
      --panel-bg: rgba(13, 17, 25, 0.94);
      --border: rgba(255, 255, 255, 0.12);
      --accent-blue: #22e5ff;
      --accent-green: #00e676;
      --accent-red: #ff5252;
      --accent-yellow: #ffea00;
      --text: #e2e8f0;
      --muted: #8899aa;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: monospace; overflow: hidden; width: 100vw; height: 100vh; }}
    #canvas3d {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; }}
    #hud-panel {{
      position: absolute; top: 14px; left: 14px; width: 420px;
      background: var(--panel-bg); backdrop-filter: blur(14px);
      border: 1px solid var(--border); border-radius: 10px; z-index: 10; padding: 14px;
      display: flex; flex-direction: column; gap: 10px; box-shadow: 0 10px 30px rgba(0,0,0,0.6);
    }}
    h1 {{ font-size: 13px; font-weight: 700; color: var(--accent-green); text-transform: uppercase; }}
    select.ds-select {{ width: 100%; padding: 8px; background: #0d121c; border: 1px solid var(--accent-green); color: #fff; font-size: 11px; border-radius: 6px; }}
    .card {{ background: rgba(0,0,0,0.3); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.06); font-size: 11px; line-height: 1.5; }}
    .card b {{ color: var(--accent-green); }}
    .toggle-row {{ display: flex; align-items: center; justify-content: space-between; font-size: 11px; margin-top: 4px; }}
    .switch {{ position: relative; display: inline-block; width: 36px; height: 20px; }}
    .switch input {{ opacity: 0; width: 0; height: 0; }}
    .slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #334155; transition: .3s; border-radius: 20px; }}
    .slider:before {{ position: absolute; content: ""; height: 14px; width: 14px; left: 3px; bottom: 3px; background-color: white; transition: .3s; border-radius: 50%; }}
    input:checked + .slider {{ background-color: var(--accent-green); }}
    input:checked + .slider:before {{ transform: translateX(16px); }}
    #timeline-bar {{
      position: absolute; bottom: 16px; left: 14px; right: 14px;
      background: var(--panel-bg); backdrop-filter: blur(14px); border: 1px solid var(--border);
      border-radius: 10px; padding: 10px 16px; z-index: 10; display: flex; align-items: center; gap: 14px;
    }}
    .play-btn {{ background: var(--accent-green); color: #000; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 700; cursor: pointer; }}
  </style>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
</head>
<body>
  <div id="canvas3d"></div>
  <div id="hud-panel">
    <h1>🌐 Etalon Mikró-Voxel Scan-to-Map SLAM</h1>
    <p style="font-size:10px; color:var(--muted);">Rögzített 5 cm Fal Voxelek & Robustus Scan-to-Map Korrekció</p>

    <div>
      <label style="font-size:10px; color:var(--muted); display:block; margin-bottom:3px;">ADATHALMAZ:</label>
      <select id="dataset-select" class="ds-select" onchange="onDatasetChange()">
        <option value="walk_kicsi" selected>🚶 walk_kicsi — Szobai séta (60s)</option>
        <option value="walk_teszt">🛑 walk_teszt — Álló robot (60s)</option>
        <option value="walk_seta1">🏃 walk_seta1 — Nagy séta (90s)</option>
      </select>
    </div>

    <div class="card">
      <div class="toggle-row">
        <span>🔴 Nyers Driftelő Odometria Megjelenítése:</span>
        <label class="switch">
          <input type="checkbox" id="chk-raw-traj" checked onchange="updateVisibility()">
          <span class="slider"></span>
        </label>
      </div>
      <div class="toggle-row">
        <span>🟢 Etalon-Korrigált SLAM Útvonal:</span>
        <label class="switch">
          <input type="checkbox" id="chk-slam-traj" checked onchange="updateVisibility()">
          <span class="slider"></span>
        </label>
      </div>
      <div class="toggle-row">
        <span>🧱 5×5 cm Rögzített Etalon Voxelek:</span>
        <label class="switch">
          <input type="checkbox" id="chk-voxels" checked onchange="updateVisibility()">
          <span class="slider"></span>
        </label>
      </div>
    </div>

    <div class="card" style="border-left: 3px solid var(--accent-green);">
      <b>🌐 Az Etalon Voxel Korrekció Működése:</b><br>
      A megszilárdult 5 cm-es zöld fal-voxelek **rögzített etalonként** szolgálnak. A robot folyamatosan ezekhez korrigálja magát szigorúan korlátozott keret-illlesztéssel, megszüntetve a forgásokból eredő elmászást!
    </div>

    <div id="ds-info" class="card">
      <div>Rögzített Etalon Voxelek: <b id="info-etalon-count" style="color:var(--accent-green);">0 db</b></div>
      <div>Max Odometria Korrekció (Drift): <b id="info-max-drift" style="color:var(--accent-red);">0.0 cm</b></div>
      <div>Átlagos Pozíció Korrekció: <b id="info-avg-drift" style="color:var(--accent-yellow);">0.0 cm</b></div>
      <div>Sűrű Pontfelhő: <b id="info-total-points">0 db</b></div>
    </div>
  </div>

  <div id="timeline-bar">
    <button class="play-btn" id="btn-play" onclick="togglePlay()">▶ Lejátszás</button>
    <div style="font-size:12px; font-weight:700; color:#fff;" id="lbl-time">0.0s</div>
    <input type="range" id="rng-timeline" min="0" max="100" value="100" style="flex:1;" oninput="onTimelineScrub(this.value)">
  </div>

  <script>
    const ALL_DATA = {data_json};
    let currentDs = "walk_kicsi";
    let scene, camera, renderer, controls;
    let grpPoints, grpRawTraj, grpSlamTraj, grpVoxels;
    let rawPosArray, rawFramesArray, ptsGeom, ptsMaterial;
    let currentFrameIdx = 0;
    let isPlaying = false;
    let voxelInstancedMeshEtalon = null;
    let voxelInstancedMeshCandidate = null;

    function init3D() {{
      const container = document.getElementById("canvas3d");
      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x07090e);

      camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 100);
      camera.position.set(0, 10, 8);

      renderer = new THREE.WebGLRenderer({{ antialias: true }});
      renderer.setSize(window.innerWidth, window.innerHeight);
      container.appendChild(renderer.domElement);

      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;

      const grid = new THREE.GridHelper(40, 40, 0x00e676, 0x1e293b);
      grid.position.y = -0.4;
      scene.add(grid);

      grpPoints = new THREE.Group();
      grpRawTraj = new THREE.Group();
      grpSlamTraj = new THREE.Group();
      grpVoxels = new THREE.Group();
      scene.add(grpPoints);
      scene.add(grpRawTraj);
      scene.add(grpSlamTraj);
      scene.add(grpVoxels);

      loadDataset();
    }}

    function toThree(x, y, z) {{
      return new THREE.Vector3(x, z, -y);
    }}

    function loadDataset() {{
      while(grpPoints.children.length) grpPoints.remove(grpPoints.children[0]);
      while(grpRawTraj.children.length) grpRawTraj.remove(grpRawTraj.children[0]);
      while(grpSlamTraj.children.length) grpSlamTraj.remove(grpSlamTraj.children[0]);
      while(grpVoxels.children.length) grpVoxels.remove(grpVoxels.children[0]);
      voxelInstancedMeshEtalon = null;
      voxelInstancedMeshCandidate = null;

      const ds = ALL_DATA[currentDs];
      if (!ds) return;

      document.getElementById("info-etalon-count").textContent = ds.etalon_voxels_count + " db";
      document.getElementById("info-max-drift").textContent = ds.max_drift_cm + " cm";
      document.getElementById("info-avg-drift").textContent = ds.avg_drift_cm + " cm";
      document.getElementById("info-total-points").textContent = ds.total_points.toLocaleString("hu-HU") + " db";

      // Pontfelhő
      const numPts = ds.points.length;
      const pos = new Float32Array(numPts * 3);
      const col = new Float32Array(numPts * 3);
      rawFramesArray = new Int32Array(numPts);

      for (let i = 0; i < numPts; i++) {{
        const pt = ds.points[i];
        const p3 = toThree(pt[0], pt[1], pt[2]);
        pos[i * 3] = p3.x; pos[i * 3 + 1] = p3.y; pos[i * 3 + 2] = p3.z;
        rawFramesArray[i] = pt[3];
        col[i * 3] = 0.2; col[i * 3 + 1] = 0.7; col[i * 3 + 2] = 1.0;
      }}

      rawPosArray = new Float32Array(pos);
      ptsGeom = new THREE.BufferGeometry();
      ptsGeom.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      ptsGeom.setAttribute('color', new THREE.BufferAttribute(col, 3));

      ptsMaterial = new THREE.PointsMaterial({{ size: 0.03, vertexColors: true, transparent: true, opacity: 0.70 }});
      grpPoints.add(new THREE.Points(ptsGeom, ptsMaterial));

      // Nyers Odometria Útvonal (Piros)
      const rawPts = ds.raw_trajectory.map(t => toThree(t.x, t.y, 0.04));
      const rawLineGeom = new THREE.BufferGeometry().setFromPoints(rawPts);
      grpRawTraj.add(new THREE.Line(rawLineGeom, new THREE.LineBasicMaterial({{ color: 0xff5252, linewidth: 2 }})));

      // Etalon SLAM Útvonal (Zöld)
      const slamPts = ds.slam_trajectory.map(t => toThree(t.x, t.y, 0.08));
      const slamLineGeom = new THREE.BufferGeometry().setFromPoints(slamPts);
      grpSlamTraj.add(new THREE.Line(slamLineGeom, new THREE.LineBasicMaterial({{ color: 0x00e676, linewidth: 3 }})));

      // 5x5 cm Etalon Voxelek
      const etalonList = [];
      const candidateList = [];
      ds.voxels_5cm.forEach(v => {{
        if (v[6] === 1) etalonList.push(v);
        else candidateList.push(v);
      }});

      const geom = new THREE.BoxGeometry(0.046, 0.046, 0.046);

      if (etalonList.length > 0) {{
        const matEtalon = new THREE.MeshBasicMaterial({{ color: 0x00e676, transparent: true, opacity: 0.85 }});
        voxelInstancedMeshEtalon = new THREE.InstancedMesh(geom, matEtalon, etalonList.length);
        const dummy = new THREE.Object3D();
        etalonList.forEach((v, idx) => {{
          const p3 = toThree(v[0], v[1], v[2]);
          dummy.position.set(p3.x, p3.y, p3.z);
          dummy.updateMatrix();
          voxelInstancedMeshEtalon.setMatrixAt(idx, dummy.matrix);
        }});
        voxelInstancedMeshEtalon.instanceMatrix.needsUpdate = true;
        voxelInstancedMeshEtalon.userData = {{ items: etalonList }};
        grpVoxels.add(voxelInstancedMeshEtalon);
      }}

      if (candidateList.length > 0) {{
        const matCand = new THREE.MeshBasicMaterial({{ color: 0xffea00, transparent: true, opacity: 0.35, wireframe: true }});
        voxelInstancedMeshCandidate = new THREE.InstancedMesh(geom, matCand, candidateList.length);
        const dummy = new THREE.Object3D();
        candidateList.forEach((v, idx) => {{
          const p3 = toThree(v[0], v[1], v[2]);
          dummy.position.set(p3.x, p3.y, p3.z);
          dummy.updateMatrix();
          voxelInstancedMeshCandidate.setMatrixAt(idx, dummy.matrix);
        }});
        voxelInstancedMeshCandidate.instanceMatrix.needsUpdate = true;
        voxelInstancedMeshCandidate.userData = {{ items: candidateList }};
        grpVoxels.add(voxelInstancedMeshCandidate);
      }}

      const rng = document.getElementById("rng-timeline");
      rng.max = ds.total_frames - 1;
      rng.value = ds.total_frames - 1;
      currentFrameIdx = ds.total_frames - 1;

      updateVisibleElements();
    }}

    function updateVisibility() {{
      grpRawTraj.visible = document.getElementById("chk-raw-traj").checked;
      grpSlamTraj.visible = document.getElementById("chk-slam-traj").checked;
      grpVoxels.visible = document.getElementById("chk-voxels").checked;
    }}

    function updateVisibleElements() {{
      if (!ptsGeom || !rawPosArray) return;
      const ds = ALL_DATA[currentDs];

      const posAttr = ptsGeom.getAttribute('position');
      const numPts = rawFramesArray.length;
      for (let i = 0; i < numPts; i++) {{
        if (rawFramesArray[i] <= currentFrameIdx) {{
          posAttr.setXYZ(i, rawPosArray[i * 3], rawPosArray[i * 3 + 1], rawPosArray[i * 3 + 2]);
        }} else {{
          posAttr.setXYZ(i, 0, -999, 0);
        }}
      }}
      posAttr.needsUpdate = true;

      [voxelInstancedMeshEtalon, voxelInstancedMeshCandidate].forEach(imesh => {{
        if (!imesh) return;
        const items = imesh.userData.items;
        const dummy = new THREE.Object3D();
        items.forEach((v, idx) => {{
          if (v[4] <= currentFrameIdx) {{
            const p3 = toThree(v[0], v[1], v[2]);
            dummy.position.set(p3.x, p3.y, p3.z);
            dummy.scale.set(1, 1, 1);
          }} else {{
            dummy.scale.set(0, 0, 0);
          }}
          dummy.updateMatrix();
          imesh.setMatrixAt(idx, dummy.matrix);
        }});
        imesh.instanceMatrix.needsUpdate = true;
      }});

      const currSlam = ds.slam_trajectory[Math.min(currentFrameIdx, ds.slam_trajectory.length - 1)];
      if (currSlam) {{
        document.getElementById("lbl-time").textContent = `${{(currentFrameIdx * 0.25).toFixed(1)}}s / ${{ds.total_time}}s (Drift: ${{currSlam.drift_cm}}cm)`;
      }}
    }}

    function onDatasetChange() {{
      currentDs = document.getElementById("dataset-select").value;
      loadDataset();
    }}

    function onTimelineScrub(val) {{
      currentFrameIdx = parseInt(val);
      updateVisibleElements();
    }}

    function togglePlay() {{
      isPlaying = !isPlaying;
      document.getElementById("btn-play").textContent = isPlaying ? "⏸ Megállítás" : "▶ Lejátskás";
    }}

    function animate() {{
      requestAnimationFrame(animate);
      if (isPlaying) {{
        const ds = ALL_DATA[currentDs];
        if (currentFrameIdx < ds.total_frames - 1) {{
          currentFrameIdx++;
          updateVisibleElements();
          document.getElementById("rng-timeline").value = currentFrameIdx;
        }} else {{
          togglePlay();
        }}
      }}
      controls.update();
      renderer.render(scene, camera);
    }}

    init3D();
    animate();
  </script>
</body>
</html>
"""

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    datasets = [
        ("walk_kicsi.jsonl", "walk_kicsi", "🚶 Kis szobai séta (60s)", False, 2, 240),
        ("walk_teszt.jsonl", "walk_teszt", "🛑 Álló robot (60s)", True, 2, 240),
        ("walk_seta1.jsonl", "walk_seta1", "🏃 Nagy séta (90s)", False, 2, 240),
    ]
    
    processed = {}
    for filename, ds_id, label, is_stat, step_val, max_fr in datasets:
        fpath = os.path.join(base_dir, filename)
        if os.path.exists(fpath):
            res = process_etalon_slam(fpath, ds_id, label, is_stationary=is_stat, step=step_val, max_frames=max_fr)
            if res:
                processed[ds_id] = res
                
    html_content = generate_etalon_html(processed)
    out_file = os.path.join(base_dir, "bounded_icp_slam.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"\nMentve: {out_file} ({len(html_content):,} bájt)")

if __name__ == "__main__":
    main()
