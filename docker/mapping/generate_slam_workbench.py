"""
NERO_GO2 — Interaktív SLAM Workbench (Választott Elsődleges Algoritmus: KISS-ICP Pure LiDAR Odometry)
Beállítások:
- Elsődleges Algoritmus: 🚀 KISS-ICP (PRBonn Pure LiDAR Odometry)
- Default Gyro Skála: 0.99x
- Default Yaw Offset: 96.0°
- Default Voxel Méret: 2 cm
"""

import json
import math
import os
import sys
import numpy as np
from scipy.spatial import cKDTree

from kiss_icp.kiss_icp import KissICP
from kiss_icp.config import KISSConfig
import small_gicp

def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi

def compute_pure_lidar_trajectories(selected_frames):
    config = KISSConfig()
    config.mapping.voxel_size = 0.15
    config.data.max_range = 12.0
    config.data.min_range = 0.35
    config.data.deskew = False
    kiss_odo = KissICP(config)
    
    kiss_poses = []
    gicp_poses = []
    
    T_gicp = np.eye(4, dtype=np.float64)
    last_valid_pts = None
    
    for fr in selected_frames:
        pts_list = fr.get("points", [])
        if not pts_list:
            kiss_poses.append((0.0, 0.0, 0.0))
            gicp_poses.append((0.0, 0.0, 0.0))
            continue
            
        pts = np.array(pts_list, dtype=np.float64)[:, :3]
        dist = np.hypot(pts[:, 0], pts[:, 1])
        valid = (dist >= 0.35) & (dist <= 12.0) & (pts[:, 2] > -0.6) & (pts[:, 2] < 2.0)
        valid_pts = pts[valid]
        
        if len(valid_pts) < 30:
            kiss_poses.append(kiss_poses[-1] if kiss_poses else (0.0, 0.0, 0.0))
            gicp_poses.append(gicp_poses[-1] if gicp_poses else (0.0, 0.0, 0.0))
            continue
            
        # KISS-ICP
        ts = np.zeros(len(valid_pts), dtype=np.float64)
        kiss_odo.register_frame(valid_pts, ts)
        kp = kiss_odo.last_pose
        kx, ky = float(kp[0, 3]), float(kp[1, 3])
        kyaw = float(wrap_angle(math.atan2(kp[1, 0], kp[0, 0])))
        kiss_poses.append((round(kx, 4), round(ky, 4), round(kyaw, 4)))
        
        # Small-GICP
        if last_valid_pts is not None:
            res = small_gicp.align(
                last_valid_pts,
                valid_pts,
                np.eye(4, dtype=np.float64),
                registration_type="VGICP",
                voxel_resolution=0.15,
                max_correspondence_distance=0.5,
                max_iterations=20
            )
            T_gicp = T_gicp @ res.T_target_source
            
        last_valid_pts = valid_pts
        gx, gy = float(T_gicp[0, 3]), float(T_gicp[1, 3])
        gyaw = float(wrap_angle(math.atan2(T_gicp[1, 0], T_gicp[0, 0])))
        gicp_poses.append((round(gx, 4), round(gy, 4), round(gyaw, 4)))
        
    return kiss_poses, gicp_poses

def load_dataset_frames(filepath, max_frames=200, pts_per_frame=400):
    if not os.path.exists(filepath):
        return []
    
    raw_lines = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            raw_lines.append(json.loads(line))
            if len(raw_lines) >= max_frames * 2:
                break
                
    step = max(1, len(raw_lines) // max_frames)
    selected_frames = raw_lines[::step][:max_frames]
    
    print(f"  -> Számítás: KISS-ICP és Small-GICP tiszta LiDAR trajektóriák ({len(selected_frames)} képkocka)...")
    kiss_poses, gicp_poses = compute_pure_lidar_trajectories(selected_frames)
    
    etalon_centroids = []
    etalon_tree = None
    voxel_grid = {}
    voxel_size = 0.02
    
    processed_frames = []
    slam_x, slam_y, slam_yaw = 0.0, 0.0, 0.0
    last_raw = None
    
    for idx, fr in enumerate(selected_frames):
        pts_list = fr.get("points", [])
        if not pts_list:
            continue
            
        pts_raw = np.array(pts_list, dtype=np.float32).reshape(-1, 4)
        xyz = pts_raw[:, :3]
        d = np.hypot(xyz[:, 0], xyz[:, 1])
        valid = (d > 0.35) & (d < 8.0) & (xyz[:, 2] > -0.5) & (xyz[:, 2] < 2.0)
        valid_xyz = xyz[valid]
        
        if len(valid_xyz) == 0:
            continue
            
        if len(valid_xyz) > pts_per_frame:
            sub_idx = np.random.choice(len(valid_xyz), pts_per_frame, replace=False)
            valid_xyz = valid_xyz[sub_idx]
            
        x_raw = float(fr.get("x", 0.0) or 0.0)
        y_raw = float(fr.get("y", 0.0) or 0.0)
        z_raw = float(fr.get("z", 0.0) or 0.0)
        yaw_raw = float(wrap_angle(fr.get("yaw", 0.0) or 0.0))
        roll = float(fr.get("roll", 0.0) or 0.0)
        pitch = float(fr.get("pitch", 0.0) or 0.0)
        
        if last_raw is None:
            slam_x, slam_y, slam_yaw = x_raw, y_raw, yaw_raw
            icp_dx, icp_dy, icp_dyaw = 0.0, 0.0, 0.0
        else:
            dx = x_raw - last_raw[0]
            dy = y_raw - last_raw[1]
            dyaw = wrap_angle(yaw_raw - last_raw[2])
            
            cos_p = math.cos(last_raw[2])
            sin_p = math.sin(last_raw[2])
            dx_b = cos_p * dx + sin_p * dy
            dy_b = -sin_p * dx + cos_p * dy
            
            slam_x += math.cos(slam_yaw) * dx_b - math.sin(slam_yaw) * dy_b
            slam_y += math.sin(slam_yaw) * dx_b + math.cos(slam_yaw) * dy_b
            slam_yaw = wrap_angle(slam_yaw + dyaw)
            
            icp_dx, icp_dy, icp_dyaw = 0.0, 0.0, 0.0
            if etalon_tree is not None and len(etalon_centroids) > 50 and idx % 2 == 0:
                cy, sy = math.cos(slam_yaw), math.sin(slam_yaw)
                rot = np.array([[cy, -sy], [sy, cy]], dtype=np.float32)
                pts_world_xy = valid_xyz[:, :2] @ rot.T + np.array([slam_x, slam_y], dtype=np.float32)
                
                non_floor = valid_xyz[:, 2] > -0.20
                non_floor_xy = pts_world_xy[non_floor]
                
                if len(non_floor_xy) > 25:
                    curr_xy = non_floor_xy.copy()
                    d_R = np.eye(2, dtype=np.float32)
                    d_t = np.zeros(2, dtype=np.float32)
                    etalon_arr = np.array(etalon_centroids, dtype=np.float32)
                    
                    for _ in range(4):
                        dists, idxs = etalon_tree.query(curr_xy)
                        valid_m = dists < 0.25
                        if np.sum(valid_m) < 20:
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
                        
                    icp_dyaw = float(wrap_angle(math.atan2(d_R[1, 0], d_R[0, 0])))
                    icp_dx = float(d_t[0])
                    icp_dy = float(d_t[1])
                    
                    slam_x += np.clip(icp_dx, -0.15, 0.15)
                    slam_y += np.clip(icp_dy, -0.15, 0.15)
                    slam_yaw = wrap_angle(slam_yaw + np.clip(icp_dyaw, -0.05, 0.05))

        last_raw = (x_raw, y_raw, yaw_raw)
        
        cy, sy = math.cos(slam_yaw), math.sin(slam_yaw)
        rot = np.array([[cy, -sy], [sy, cy]], dtype=np.float32)
        pts_w = valid_xyz[:, :2] @ rot.T + np.array([slam_x, slam_y], dtype=np.float32)
        for p_idx in range(len(pts_w)):
            if valid_xyz[p_idx, 2] > -0.20:
                vx = int(round(pts_w[p_idx, 0] / voxel_size))
                vy = int(round(pts_w[p_idx, 1] / voxel_size))
                vk = (vx, vy)
                if vk not in voxel_grid:
                    voxel_grid[vk] = 1
                    etalon_centroids.append((vx * voxel_size, vy * voxel_size))
                    
        if len(etalon_centroids) > 50 and idx % 5 == 0:
            etalon_tree = cKDTree(np.array(etalon_centroids, dtype=np.float32))

        kp = kiss_poses[idx] if idx < len(kiss_poses) else (0.0, 0.0, 0.0)
        gp = gicp_poses[idx] if idx < len(gicp_poses) else (0.0, 0.0, 0.0)

        processed_frames.append({
            "t": round(float(fr.get("t", 0.0) or 0.0), 2),
            "x": round(x_raw, 4),
            "y": round(y_raw, 4),
            "z": round(z_raw, 4),
            "yaw": round(yaw_raw, 4),
            "roll": round(roll, 4),
            "pitch": round(pitch, 4),
            "kiss_x": kp[0],
            "kiss_y": kp[1],
            "kiss_yaw": kp[2],
            "gicp_x": gp[0],
            "gicp_y": gp[1],
            "gicp_yaw": gp[2],
            "icp_dx": round(icp_dx, 4),
            "icp_dy": round(icp_dy, 4),
            "icp_dyaw": round(icp_dyaw, 4),
            "pts": np.round(valid_xyz, 3).tolist()
        })
        
    return processed_frames

def generate_workbench():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    datasets = {
        "walk_kicsi": ("walk_kicsi.jsonl", "🚶 Kis szobai séta (60s)"),
        "walk_seta1": ("walk_seta1.jsonl", "🏃 Nagy séta (90s)"),
        "walk_teszt": ("walk_teszt.jsonl", "🛑 Álló robot (60s)"),
        "walk_live_rect": ("walk_live_rect_2026-09-21_v2.jsonl", "🤖 ÉLŐ robot, akadálykerülő mód (74s)"),
    }
    
    ds_data = {}
    for ds_id, (fname, label) in datasets.items():
        fpath = os.path.join(base_dir, fname)
        if os.path.exists(fpath):
            print(f"Betöltés & SLAM/Odometriák Kiszámítása: {ds_id} ({fname})...")
            frames = load_dataset_frames(fpath, max_frames=200, pts_per_frame=400)
            total_pts = sum(len(fr["pts"]) for fr in frames)
            print(f"  -> {len(frames)} képkocka, összesen {total_pts:,} pont betöltve!")
            ds_data[ds_id] = {
                "label": label,
                "frames": frames
            }

    json_datasets = json.dumps(ds_data)

    html_template = """<!DOCTYPE html>
<html lang="hu">
<head>
  <meta charset="UTF-8">
  <title>NERO GO2 — KISS-ICP Pure LiDAR SLAM Workbench</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
  <style>
    body { margin: 0; padding: 0; background-color: #0c0f12; color: #e0e6ed; font-family: 'Segoe UI', Roboto, Helvetica, sans-serif; overflow: hidden; }
    #canvas-container { width: 100vw; height: 100vh; position: absolute; top: 0; left: 0; z-index: 1; }
    
    .panel {
      position: absolute;
      top: 15px;
      left: 15px;
      z-index: 10;
      background: rgba(16, 22, 30, 0.94);
      border: 1px solid #1e293b;
      border-radius: 12px;
      padding: 18px;
      width: 420px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.6);
      backdrop-filter: blur(8px);
      max-height: 92vh;
      overflow-y: auto;
    }
    
    h2 { margin: 0 0 4px 0; font-size: 1.15rem; color: #38bdf8; text-transform: uppercase; letter-spacing: 1px; }
    .subtitle { font-size: 0.8rem; color: #4ade80; font-weight: 600; margin-bottom: 14px; }
    
    .control-group { margin-bottom: 12px; background: rgba(30, 41, 59, 0.4); padding: 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); }
    .control-label { font-size: 0.82rem; font-weight: 600; color: #cbd5e1; display: flex; justify-content: space-between; margin-bottom: 6px; }
    .control-val { font-family: monospace; color: #38bdf8; }
    
    input[type=range] {
      width: 100%;
      -webkit-appearance: none;
      background: #334155;
      height: 6px;
      border-radius: 3px;
      outline: none;
    }
    input[type=range]::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      background: #38bdf8;
      cursor: pointer;
      box-shadow: 0 0 8px rgba(56, 189, 248, 0.6);
    }
    
    select, button {
      width: 100%;
      background: #1e293b;
      border: 1px solid #334155;
      color: #f8fafc;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 0.85rem;
      cursor: pointer;
      outline: none;
      transition: all 0.2s;
    }
    select:hover, button:hover { border-color: #38bdf8; background: #334155; }
    
    .btn-row { display: flex; gap: 8px; margin-top: 10px; }
    .btn-row button { flex: 1; font-weight: 600; }
    
    .metrics-box {
      margin-top: 15px;
      padding: 12px;
      background: rgba(15, 23, 42, 0.8);
      border-radius: 8px;
      border-left: 4px solid #4ade80;
      font-size: 0.8rem;
    }
    .metric-row { display: flex; justify-content: space-between; margin-bottom: 4px; }
    
    .legend {
      position: absolute;
      bottom: 20px;
      right: 20px;
      z-index: 10;
      background: rgba(16, 22, 30, 0.85);
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 12px 16px;
      font-size: 0.8rem;
    }
    .legend-item { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .legend-color { width: 12px; height: 12px; border-radius: 3px; }
  </style>
</head>
<body>
  <div id="canvas-container"></div>
  
  <div class="panel">
    <h2>🎛️ SLAM Workbench</h2>
    <div class="subtitle">✅ Választott Algoritmus: KISS-ICP (PRBonn Pure LiDAR)</div>
    
    <div class="control-group">
      <div class="control-label">📂 Adatmozaik Adatsor:</div>
      <select id="sel-dataset" onchange="changeDataset()"></select>
    </div>
    
    <div class="control-group">
      <div class="control-label">🔄 Algoritmus / Trajektória Mód:</div>
      <select id="sel-mode" onchange="updateSLAM()">
        <option value="kiss_icp" selected>🚀 KISS-ICP (PRBonn Pure LiDAR Odometry - VÁLASZTOTT)</option>
        <option value="small_gicp">⚡ Small-GICP (Voxelized GICP Scan-to-Scan)</option>
        <option value="raw_odo">📐 Nyers Korrigált Odometria (0.99x, 96.0°)</option>
        <option value="loop_closure">🔗 Pose Graph Loop Closure SLAM</option>
      </select>
    </div>

    <div class="control-group">
      <div class="control-label">🧭 Gyro / Yaw Skála (Nyers módhoz): <span class="control-val" id="val-yaw-scale">0.99x</span></div>
      <input type="range" id="rng-yaw-scale" min="0.50" max="1.50" step="0.01" value="0.99" oninput="updateSLAM()">
    </div>
    
    <div class="control-group">
      <div class="control-label">📐 LiDAR-IMU Yaw Offset (Nyers módhoz): <span class="control-val" id="val-yaw-offset">96.0°</span></div>
      <input type="range" id="rng-yaw-offset" min="-180" max="180" step="0.5" value="96.0" oninput="updateSLAM()">
    </div>

    <div class="control-group">
      <div class="control-label">🧱 Voxel Rács Térkép Méret: <span class="control-val" id="val-voxel-size">2 cm</span></div>
      <input type="range" id="rng-voxel-size" min="1" max="20" step="1" value="2" oninput="updateSLAM()">
    </div>

    <div class="control-group">
      <div class="control-label">⏱️ Idővonal / Léptetés: <span class="control-val" id="val-frame-idx">0 / 0</span></div>
      <input type="range" id="rng-frame-idx" min="0" max="100" value="100" oninput="updateTimeline()">
      <div class="btn-row">
        <button id="btn-play" onclick="togglePlay()">▶ Lejátszás</button>
        <button onclick="resetSliders()">🔄 Visszaállítás</button>
      </div>
    </div>
    
    <div class="metrics-box">
      <div class="metric-row"><span>Képkockák Pontszáma:</span><b id="m-pts" style="color:#38bdf8;">0 db</b></div>
      <div class="metric-row"><span>Egyedi Voxelek a Térképen:</span><b id="m-vox" style="color:#4ade80;">0 db</b></div>
      <div class="metric-row"><span>Aktív Algoritmus Mód:</span><b id="m-mode" style="color:#4ade80;">KISS-ICP Pure LiDAR</b></div>
      <div class="metric-row"><span>JS Számítási Idő:</span><b id="m-time" style="color:#a78bfa;">0 ms</b></div>
    </div>
  </div>
  
  <div class="legend">
    <div class="legend-item"><div class="legend-color" style="background:#ef4444;"></div> Piros: Nyers Odometria Trajektória</div>
    <div class="legend-item"><div class="legend-color" style="background:#22c55e;"></div> Zöld: Választott KISS-ICP Trajektória</div>
    <div class="legend-item"><div class="legend-color" style="background:#38bdf8;"></div> Kék pontok: 3D Voxel Térkép (Falak)</div>
  </div>

  <script>
    const DATASETS = __DATASETS_JSON__;

    let scene, camera, renderer, controls;
    let pointCloudMesh, rawTrajectoryLine, activeTrajectoryLine, robotMarker;
    let currentDatasetKey = "walk_kicsi";
    let isPlaying = false;
    let playInterval = null;

    function init3D() {
      const container = document.getElementById("canvas-container");
      scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0c0f12);

      camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 100);
      camera.position.set(0, -12, 14);
      camera.up.set(0, 0, 1);

      renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setSize(window.innerWidth, window.innerHeight);
      renderer.setPixelRatio(window.devicePixelRatio);
      container.appendChild(renderer.domElement);

      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.target.set(0, 0, 0);
      controls.update();

      const gridHelper = new THREE.GridHelper(30, 30, 0x334155, 0x1e293b);
      gridHelper.rotation.x = Math.PI / 2;
      scene.add(gridHelper);

      // Trajektória vonalak
      const rawGeo = new THREE.BufferGeometry();
      rawTrajectoryLine = new THREE.Line(rawGeo, new THREE.LineBasicMaterial({ color: 0xef4444, linewidth: 2 }));
      scene.add(rawTrajectoryLine);

      const activeGeo = new THREE.BufferGeometry();
      activeTrajectoryLine = new THREE.Line(activeGeo, new THREE.LineBasicMaterial({ color: 0x22c55e, linewidth: 3 }));
      scene.add(activeTrajectoryLine);

      // Robot Jelölő
      const robGeo = new THREE.ConeGeometry(0.25, 0.6, 8);
      robGeo.rotateX(Math.PI / 2);
      robotMarker = new THREE.Mesh(robGeo, new THREE.MeshBasicMaterial({ color: 0xfacc15 }));
      scene.add(robotMarker);

      window.addEventListener("resize", () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
      });

      // Populate dataset selector
      const sel = document.getElementById("sel-dataset");
      sel.innerHTML = "";
      for (let key in DATASETS) {
        let opt = document.createElement("option");
        opt.value = key;
        opt.innerText = DATASETS[key].label;
        sel.appendChild(opt);
      }

      changeDataset();
    }

    function changeDataset() {
      currentDatasetKey = document.getElementById("sel-dataset").value;
      const frames = DATASETS[currentDatasetKey].frames;
      const rngFrame = document.getElementById("rng-frame-idx");
      rngFrame.max = frames.length - 1;
      rngFrame.value = frames.length - 1;
      updateSLAM();
    }

    function wrapAngle(a) {
      return (a + Math.PI) % (2 * Math.PI) - Math.PI;
    }

    function updateSLAM() {
      const t0 = performance.now();
      const yawScale = parseFloat(document.getElementById("rng-yaw-scale").value);
      const yawOffsetDeg = parseFloat(document.getElementById("rng-yaw-offset").value);
      const yawOffsetRad = yawOffsetDeg * Math.PI / 180.0;
      const mode = document.getElementById("sel-mode").value;
      const voxelCm = parseFloat(document.getElementById("rng-voxel-size").value);
      const voxelM = voxelCm / 100.0;
      const maxFrameIdx = parseInt(document.getElementById("rng-frame-idx").value);

      document.getElementById("val-yaw-scale").innerText = yawScale.toFixed(2) + "x";
      document.getElementById("val-yaw-offset").innerText = yawOffsetDeg.toFixed(1) + "°";
      document.getElementById("val-voxel-size").innerText = voxelCm + " cm";

      let modeText = "🚀 KISS-ICP Pure LiDAR (VÁLASZTOTT)";
      if (mode === "small_gicp") modeText = "Small-GICP (VGICP)";
      else if (mode === "raw_odo") modeText = "Nyers Korrigált Odometria";
      else if (mode === "loop_closure") modeText = "Pose Graph Loop Closure";
      document.getElementById("m-mode").innerText = modeText;

      const frames = DATASETS[currentDatasetKey].frames;
      if (!frames || frames.length === 0) return;

      const activeFrames = frames.slice(0, maxFrameIdx + 1);
      document.getElementById("val-frame-idx").innerText = activeFrames.length + " / " + frames.length;

      const rawPoses = [];
      const activePoses = [];
      const mapVoxels = new Map();

      let totalPtsInMap = 0;

      for (let i = 0; i < activeFrames.length; i++) {
        const fr = activeFrames[i];
        
        // 1. Raw odometry with sliders
        if (i === 0) {
          const initYaw = fr.yaw * yawScale + yawOffsetRad;
          rawPoses.push([fr.x, fr.y, initYaw]);
        } else {
          const prevFr = activeFrames[i - 1];
          const rawYawPrev = prevFr.yaw * yawScale + yawOffsetRad;
          const rawYawCurr = fr.yaw * yawScale + yawOffsetRad;
          const dyawRaw = wrapAngle(rawYawCurr - rawYawPrev);

          const dxOdo = fr.x - prevFr.x;
          const dyOdo = fr.y - prevFr.y;

          const cosP = Math.cos(rawYawPrev);
          const sinP = Math.sin(rawYawPrev);
          const dxBody = cosP * dxOdo + sinP * dyOdo;
          const dyBody = -sinP * dxOdo + cosP * dyOdo;

          const rawLast = rawPoses[rawPoses.length - 1];
          const rawNextYaw = wrapAngle(rawLast[2] + dyawRaw);
          const rawNextX = rawLast[0] + Math.cos(rawLast[2]) * dxBody - Math.sin(rawLast[2]) * dyBody;
          const rawNextY = rawLast[1] + Math.sin(rawLast[2]) * dxBody + Math.cos(rawLast[2]) * dyBody;
          rawPoses.push([rawNextX, rawNextY, rawNextYaw]);
        }

        // 2. Select pose based on chosen algorithm mode
        if (mode === "kiss_icp") {
          activePoses.push([fr.kiss_x || 0.0, fr.kiss_y || 0.0, fr.kiss_yaw || 0.0]);
        } else if (mode === "small_gicp") {
          activePoses.push([fr.gicp_x || 0.0, fr.gicp_y || 0.0, fr.gicp_yaw || 0.0]);
        } else if (mode === "loop_closure") {
          activePoses.push([rawPoses[i][0] + (fr.icp_dx || 0.0), rawPoses[i][1] + (fr.icp_dy || 0.0), wrapAngle(rawPoses[i][2] + (fr.icp_dyaw || 0.0))]);
        } else {
          // raw_odo
          activePoses.push([rawPoses[i][0], rawPoses[i][1], rawPoses[i][2]]);
        }
      }

      // Loop Closure backward optimization if loop closure mode selected
      if (mode === "loop_closure" && activePoses.length > 30) {
        const pStart = activePoses[0];
        const pEnd = activePoses[activePoses.length - 1];
        const distLoop = Math.hypot(pStart[0] - pEnd[0], pStart[1] - pEnd[1]);
        if (distLoop < 1.5) {
          const errX = pStart[0] - pEnd[0];
          const errY = pStart[1] - pEnd[1];
          const errYaw = wrapAngle(pStart[2] - pEnd[2]);
          const N = activePoses.length;
          for (let k = 1; k < N; k++) {
            const alpha = k / parseFloat(N);
            activePoses[k][0] += alpha * errX;
            activePoses[k][1] += alpha * errY;
            activePoses[k][2] = wrapAngle(activePoses[k][2] + alpha * errYaw);
          }
        }
      }

      // Rebuild Voxel Map from Active Trajectory Poses
      for (let i = 0; i < activeFrames.length; i++) {
        const fr = activeFrames[i];
        const sPose = activePoses[i];
        const cosY = Math.cos(sPose[2]);
        const sinY = Math.sin(sPose[2]);
        const roll = fr.roll || 0, pitch = fr.pitch || 0;
        const cr = Math.cos(-roll), sr = Math.sin(-roll);

        const pts = fr.pts;
        if (pts && pts.length > 0) {
          totalPtsInMap += pts.length;
          const frZ = fr.z || 0.0;
          for (let p = 0; p < pts.length; p += 2) {
            const px = pts[p][0], py = pts[p][1], pz = pts[p][2];
            const rx = px;
            const ry = cr * py - sr * pz;
            const rz = sr * py + cr * pz;

            const wx = sPose[0] + cosY * rx - sinY * ry;
            const wy = sPose[1] + sinY * rx + cosY * ry;
            const wz = frZ + rz;

            if (isNaN(wx) || isNaN(wy) || isNaN(wz)) continue;

            const vx = Math.round(wx / voxelM);
            const vy = Math.round(wy / voxelM);
            const vz = Math.round(wz / voxelM);
            const vkey = vx + "_" + vy + "_" + vz;

            if (!mapVoxels.has(vkey)) {
              mapVoxels.set(vkey, [vx * voxelM, vy * voxelM, vz * voxelM]);
            }
          }
        }
      }

      // 3D Render Update
      const rawPts = [];
      for (let p of rawPoses) rawPts.push(p[0], p[1], 0.05);
      rawTrajectoryLine.geometry.setAttribute("position", new THREE.Float32BufferAttribute(rawPts, 3));
      rawTrajectoryLine.geometry.computeBoundingSphere();

      const activePts = [];
      for (let p of activePoses) activePts.push(p[0], p[1], 0.08);
      activeTrajectoryLine.geometry.setAttribute("position", new THREE.Float32BufferAttribute(activePts, 3));
      activeTrajectoryLine.geometry.computeBoundingSphere();

      const lastActive = activePoses[activePoses.length - 1];
      robotMarker.position.set(lastActive[0], lastActive[1], 0.15);
      robotMarker.rotation.z = lastActive[2];

      if (pointCloudMesh) scene.remove(pointCloudMesh);
      const voxelArr = Array.from(mapVoxels.values());
      const pCount = voxelArr.length;
      if (pCount > 0) {
        const pcGeo = new THREE.BufferGeometry();
        const posArray = new Float32Array(pCount * 3);
        const colArray = new Float32Array(pCount * 3);

        for (let i = 0; i < pCount; i++) {
          const vp = voxelArr[i];
          posArray[i * 3] = vp[0];
          posArray[i * 3 + 1] = vp[1];
          posArray[i * 3 + 2] = vp[2];

          const normZ = Math.min(1.0, Math.max(0.0, (vp[2] + 0.3) / 2.0));
          colArray[i * 3] = 0.2 + 0.6 * normZ;
          colArray[i * 3 + 1] = 0.6 + 0.4 * normZ;
          colArray[i * 3 + 2] = 0.9;
        }

        pcGeo.setAttribute("position", new THREE.BufferAttribute(posArray, 3));
        pcGeo.setAttribute("color", new THREE.BufferAttribute(colArray, 3));
        const pcMat = new THREE.PointsMaterial({ size: Math.max(0.03, voxelM * 0.9), vertexColors: true, sizeAttenuation: true });
        pointCloudMesh = new THREE.Points(pcGeo, pcMat);
        scene.add(pointCloudMesh);
      }

      const dt = Math.round(performance.now() - t0);
      document.getElementById("m-pts").innerText = totalPtsInMap.toLocaleString() + " db";
      document.getElementById("m-vox").innerText = mapVoxels.size.toLocaleString() + " db";
      document.getElementById("m-time").innerText = dt + " ms";
    }

    function updateTimeline() {
      updateSLAM();
    }

    function togglePlay() {
      const btn = document.getElementById("btn-play");
      const rngFrame = document.getElementById("rng-frame-idx");

      if (isPlaying) {
        clearInterval(playInterval);
        isPlaying = false;
        btn.innerText = "▶ Lejátszás";
      } else {
        if (parseInt(rngFrame.value) >= parseInt(rngFrame.max)) {
          rngFrame.value = 0;
        }
        isPlaying = true;
        btn.innerText = "⏸ Megállítás";
        playInterval = setInterval(() => {
          let val = parseInt(rngFrame.value);
          if (val < parseInt(rngFrame.max)) {
            rngFrame.value = val + 1;
            updateTimeline();
          } else {
            togglePlay();
          }
        }, 120);
      }
    }

    function resetSliders() {
      document.getElementById("rng-yaw-scale").value = 0.99;
      document.getElementById("rng-yaw-offset").value = 96.0;
      document.getElementById("sel-mode").value = "kiss_icp";
      document.getElementById("rng-voxel-size").value = 2;
      updateSLAM();
    }

    function animate() {
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }

    window.onload = () => {
      init3D();
      animate();
    };
  </script>
</body>
</html>
"""

    html_content = html_template.replace("__DATASETS_JSON__", json_datasets)

    out_file = os.path.join(base_dir, "slam_workbench.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"\nGenerálva: {out_file} ({len(html_content):,} bájt)")

if __name__ == "__main__":
    generate_workbench()
