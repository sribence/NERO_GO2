"""
NERO GO2 — KISS-ICP Pure LiDAR Odometry Pipeline
Runs KISS-ICP on raw Hesai PandarXT-16 point clouds from jsonl datasets.
No wheel odometry required for the trajectory itself -- the raw SDK pose is
used only as a coarse fast-turn *gate*, see YAW_RATE_GATE_RAD below.

Fast-turn gating -- WHY (see docker/mapping/diagnose_kiss_icp_segments.py and
the 2026-09-21 live-robot diagnostic session):
  The Hesai bridge only carries a per-FRAME timestamp, not per-point ones, so
  KISS-ICP's motion-compensated deskew has nothing to interpolate against
  (config.data.deskew stays False). During a fast in-place spin (obstacle
  avoidance mode measured up to ~1 rad/frame at 8 Hz, i.e. hundreds of deg/s)
  the ~0.1s-per-revolution LiDAR sweep itself gets significantly warped by
  the rotation happening *during* the sweep, before ICP ever sees it. Feeding
  that warped scan into scan-to-map ICP produced pose jumps 5-15x the normal
  frame-to-frame jump and wrecked the accumulated voxel map (walk_live_rect
  frames 66-79: median jump 0.014m, this window's jumps 0.1-0.6m).
  Fix (fallback, still active): when the raw SDK yaw changed more than
  YAW_RATE_GATE_RAD since the last frame, skip feeding that frame's points
  to KISS-ICP entirely (no map update), and just carry KissICP's own pose
  forward with the raw SDK's (x,y,yaw) delta as a coarse initial-guess seed.
  Once the spin settles, the next accepted frame runs a normal scan-to-*map*
  ICP alignment (not scan-to-scan), so it re-localizes against the untouched
  map rather than trusting the carried-forward raw delta blindly -- confirmed
  visually in seg_66_79_fastturn_gated.png vs the ungated seg_66_79_fastturn.png.

  2026-09-21: real fix added -- hesai_bridge.py now keeps each point's
  azimuth + recv_time, and mc_motion exposes /imu/yaw_history. deskew_points()
  below uses both to rotate every point back to a common reference orientation
  before ICP ever sees the frame, instead of dropping whole frames. The
  yaw-rate gate above stays as a fallback for when mc_motion is unreachable.
"""

import bisect
import json
import math
import sys
import time
import urllib.error
import urllib.request
import numpy as np

from kiss_icp.kiss_icp import KissICP
from kiss_icp.config import KISSConfig

# rad/frame at the dataset's ~8 Hz sample rate (~115 deg/s). Empirically
# separates the catastrophic breaks (>=0.25, up to 1.0) from normal walking
# turns (<0.25) in the 2026-09-21 live diagnostic -- see module docstring.
YAW_RATE_GATE_RAD = 0.25


def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def rotation_matrix_to_euler(R):
    sy = math.sqrt(R[0, 0] * R[0, 0] + R[1, 0] * R[1, 0])
    singular = sy < 1e-6
    if not singular:
        x = math.atan2(R[2, 1], R[2, 2])
        y = math.atan2(-R[2, 0], sy)
        z = math.atan2(R[1, 0], R[0, 0])
    else:
        x = math.atan2(-R[1, 2], R[1, 1])
        y = math.atan2(-R[2, 0], sy)
        z = 0.0
    return x, y, z


def planar_delta_matrix(dx, dy, dyaw):
    """4x4 pose delta from a raw SDK planar (x,y,yaw) step -- used only to
    carry KissICP's pose forward as a coarse guess while a frame is gated
    out, never to update the map."""
    c, s = math.cos(dyaw), math.sin(dyaw)
    T = np.eye(4, dtype=np.float64)
    T[0, 0], T[0, 1] = c, -s
    T[1, 0], T[1, 1] = s, c
    T[0, 3] = dx
    T[1, 3] = dy
    return T


def _interp_yaw(yaw_samples, t):
    """yaw_samples: [(t, yaw), ...] sorted ascending (mc_motion /imu/yaw_history).
    Linear-interpolates yaw at time t, wrapping correctly across +-pi."""
    if not yaw_samples:
        return None
    times = [s[0] for s in yaw_samples]
    if t <= times[0]:
        return yaw_samples[0][1]
    if t >= times[-1]:
        return yaw_samples[-1][1]
    i = bisect.bisect_left(times, t)
    t0, y0 = yaw_samples[i - 1]
    t1, y1 = yaw_samples[i]
    if t1 == t0:
        return y0
    frac = (t - t0) / (t1 - t0)
    return y0 + frac * wrap_angle(y1 - y0)


def deskew_points(pts_raw, yaw_samples):
    """Un-warps one Hesai sweep using each point's own recv_time (6th field,
    see hesai_bridge.py) and the robot's yaw history: rotates every point
    around Z by the yaw the robot turned *between that point's capture time
    and the sweep's reference time* (latest point in the frame), so a scan
    taken mid-turn looks like it was taken all at once. This is the real fix
    for the fast-turn scan warp described in the module docstring -- the
    YAW_RATE_GATE_RAD heuristic below is a fallback for when yaw_samples is
    unavailable (e.g. mc_motion unreachable), not the primary defense.

    Points without a recv_time (older bridge / logged jsonl data) or an
    empty yaw_samples list pass through unchanged -- always safe to call."""
    if not pts_raw or len(pts_raw[0]) < 6 or not yaw_samples:
        return pts_raw
    times = [p[5] for p in pts_raw if p[5] is not None]
    if not times:
        return pts_raw
    ref_yaw = _interp_yaw(yaw_samples, max(times))
    if ref_yaw is None:
        return pts_raw
    out = []
    for p in pts_raw:
        t = p[5]
        if t is None:
            out.append(p)
            continue
        yaw_t = _interp_yaw(yaw_samples, t)
        dyaw = wrap_angle(ref_yaw - yaw_t)
        if abs(dyaw) < 1e-9:
            out.append(p)
            continue
        x, y = p[0], p[1]
        c, s = math.cos(dyaw), math.sin(dyaw)
        out.append([c * x - s * y, s * x + c * y] + list(p[2:]))
    return out


# Match-quality gate (real fix, item 3 of the deskew plan): an anomalous
# frame-to-frame pose jump means ICP lost a confident lock on the map, even
# after deskewing. Threshold is relative to a rolling median so it adapts to
# walking vs standing-still baselines instead of one fixed number -- same
# statistic already used offline in diagnose_kiss_icp_segments.py.
JUMP_MEDIAN_WINDOW = 20
JUMP_ANOMALY_MULT = 4.0
JUMP_ANOMALY_MIN_M = 0.15

# Same idea, for orientation: a rectangular/symmetric room lets ICP lock onto
# a false ~90deg-rotated solution while the *position* barely jumps (gate
# above misses it). Track frame-to-frame |dyaw| the same way, on its own
# rolling median -- 2026-09-22 live test showed two 90deg-offset overlaid
# room outlines that the position-only gate let straight through.
YAW_JUMP_MEDIAN_WINDOW = 20
YAW_JUMP_ANOMALY_MULT = 4.0
YAW_JUMP_ANOMALY_MIN_RAD = 0.35  # ~20deg floor so normal turning frames don't trip it


def _register_and_accumulate(odo, map_voxels, pts_raw, min_range, max_range,
                              raw_pose=None, last_raw_pose=None,
                              yaw_rate_gate=YAW_RATE_GATE_RAD,
                              jump_history=None, prev_kiss_xy=None,
                              yaw_jump_history=None, prev_kiss_yaw=None):
    """Registers one frame's raw points into KISS-ICP and the voxel-map
    accumulator, unless the raw SDK pose says this frame happened during a
    fast spin (see module docstring) -- then it's skipped and the pose is
    carried forward with the raw delta instead.

    raw_pose / last_raw_pose: (x, y, yaw) from the SDK, or None to disable
    gating entirely (falls back to registering every frame unconditionally).

    jump_history / prev_kiss_xy: pass a shared list and the previous frame's
    (x, y) to enable the match-quality gate. When this frame's ICP jump is
    anomalous vs. the recent rolling median, its points are withheld from
    map_voxels (map paused/not corrupted) but pose tracking continues
    normally -- the user's own proposed design: stop registering the stream
    into the map, not lose track of where the robot is. Pass None to disable
    (old unconditional-map-update behaviour).

    Returns (entry_or_None, gated: bool). entry is the pose dict for the
    trajectory output (adds "map_paused": bool when jump_history is used);
    None when the frame had too few points OR was raw-yaw gated.
    """
    gated = False
    if raw_pose is not None and last_raw_pose is not None:
        dyaw = wrap_angle(raw_pose[2] - last_raw_pose[2])
        if abs(dyaw) >= yaw_rate_gate:
            dx = raw_pose[0] - last_raw_pose[0]
            dy = raw_pose[1] - last_raw_pose[1]
            T_delta = planar_delta_matrix(dx, dy, dyaw)
            odo.last_pose = odo.last_pose @ T_delta
            odo.last_delta = T_delta
            gated = True

    if gated:
        return None, True

    pts = np.array(pts_raw, dtype=np.float64)[:, :3]

    dist = np.hypot(pts[:, 0], pts[:, 1])
    valid = (dist >= min_range) & (dist <= max_range) & (pts[:, 2] > -0.6) & (pts[:, 2] < 2.0)
    valid_pts = pts[valid]

    if len(valid_pts) < 50:
        return None, False

    ts = np.zeros(len(valid_pts), dtype=np.float64)
    odo.register_frame(valid_pts, ts)

    pose = odo.last_pose
    x, y, z = pose[:3, 3]
    roll, pitch, yaw = rotation_matrix_to_euler(pose[:3, :3])

    map_paused = False
    if jump_history is not None:
        if prev_kiss_xy is not None:
            jump_m = math.hypot(x - prev_kiss_xy[0], y - prev_kiss_xy[1])
            med = float(np.median(jump_history)) if jump_history else 0.0
            pos_anomalous = bool(jump_history) and jump_m > max(JUMP_ANOMALY_MIN_M, med * JUMP_ANOMALY_MULT)

            yaw_anomalous = False
            if yaw_jump_history is not None and prev_kiss_yaw is not None:
                yaw_jump = abs(wrap_angle(yaw - prev_kiss_yaw))
                yaw_med = float(np.median(yaw_jump_history)) if yaw_jump_history else 0.0
                yaw_anomalous = bool(yaw_jump_history) and yaw_jump > max(
                    YAW_JUMP_ANOMALY_MIN_RAD, yaw_med * YAW_JUMP_ANOMALY_MULT)
                if not yaw_anomalous:
                    yaw_jump_history.append(yaw_jump)
                    del yaw_jump_history[:-YAW_JUMP_MEDIAN_WINDOW]
            elif yaw_jump_history is not None:
                yaw_jump_history.append(0.0)

            if pos_anomalous or yaw_anomalous:
                map_paused = True
            else:
                jump_history.append(jump_m)
                del jump_history[:-JUMP_MEDIAN_WINDOW]
        else:
            jump_history.append(0.0)
            if yaw_jump_history is not None:
                yaw_jump_history.append(0.0)

    R = pose[:3, :3]
    t_vec = pose[:3, 3]

    if not map_paused:
        world_pts = (valid_pts @ R.T) + t_vec
        for p in world_pts[::3]:  # Subsample for voxel map
            vx = int(math.floor(p[0] / 0.02))
            vy = int(math.floor(p[1] / 0.02))
            vz = int(math.floor(p[2] / 0.02))
            key = (vx, vy, vz)
            if key not in map_voxels:
                map_voxels[key] = p.tolist()

    return {
        "map_paused": map_paused,
        "x": float(x),
        "y": float(y),
        "z": float(z),
        "roll": float(roll),
        "pitch": float(pitch),
        "yaw": float(wrap_angle(yaw)),
    }, False


def run_kiss_icp_live(bridge_url="http://127.0.0.1:5003", dashboard_url="http://127.0.0.1:5002",
                       motion_url="http://127.0.0.1:9102",
                       voxel_size=0.15, max_range=12.0, min_range=0.35, poll_interval_s=0.1,
                       yaw_rate_gate=YAW_RATE_GATE_RAD):
    """Élő Hesai UDP stream feldolgozása a hesai_bridge HTTP API-n (/health,
    /lidar) keresztül. Csak akkor kér új pontfelhőt, ha a packet_count nőtt —
    a bridge stateless, nincs push/SSE, ezért pollozunk. A dashboard
    /pose_snapshot végpontját a fast-turn gate-hez kérdezi le (raw SDK yaw) --
    ha nem érhető el, a gate kikapcsol és minden keret regisztrálva lesz."""
    print(f"[KISS-ICP][LIVE] bridge={bridge_url} dashboard={dashboard_url} voxel_size={voxel_size}m "
          f"yaw_rate_gate={yaw_rate_gate}rad")

    config = KISSConfig()
    config.mapping.voxel_size = voxel_size
    config.data.max_range = max_range
    config.data.min_range = min_range
    config.data.deskew = False

    odo = KissICP(config)
    map_voxels = {}
    last_packet_count = -1
    last_raw_pose = None
    frame_count = 0
    gated_count = 0
    map_paused_count = 0
    jump_history = []
    prev_kiss_xy = None
    yaw_jump_history = []
    prev_kiss_yaw = None

    while True:
        try:
            with urllib.request.urlopen(f"{bridge_url}/health", timeout=2.0) as resp:
                health = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"[KISS-ICP][LIVE] bridge unreachable ({e}), retry in 2s")
            time.sleep(2.0)
            continue

        packet_count = health.get("packet_count", 0)
        if not health.get("connected") or packet_count == last_packet_count:
            time.sleep(poll_interval_s)
            continue
        last_packet_count = packet_count

        try:
            with urllib.request.urlopen(f"{bridge_url}/lidar", timeout=2.0) as resp:
                pts_raw = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"[KISS-ICP][LIVE] /lidar fetch failed ({e})")
            time.sleep(poll_interval_s)
            continue

        if not pts_raw:
            time.sleep(poll_interval_s)
            continue

        try:
            with urllib.request.urlopen(f"{motion_url}/imu/yaw_history", timeout=1.0) as resp:
                yh = json.loads(resp.read())
            yaw_samples = [(s["t"], s["yaw"]) for s in yh.get("samples", [])]
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            yaw_samples = []  # deskew silently no-ops, falls back to yaw-rate gate below
        pts_raw = deskew_points(pts_raw, yaw_samples)

        raw_pose = None
        if yaw_rate_gate is not None:
            try:
                with urllib.request.urlopen(f"{dashboard_url}/pose_snapshot", timeout=1.0) as resp:
                    p = json.loads(resp.read())
                raw_pose = (p.get("position_x") or 0.0, p.get("position_y") or 0.0, p.get("yaw") or 0.0)
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass  # gate silently disabled for this frame if dashboard is down

        entry, gated = _register_and_accumulate(odo, map_voxels, pts_raw, min_range, max_range,
                                                  raw_pose=raw_pose, last_raw_pose=last_raw_pose,
                                                  yaw_rate_gate=yaw_rate_gate,
                                                  jump_history=jump_history, prev_kiss_xy=prev_kiss_xy,
                                                  yaw_jump_history=yaw_jump_history, prev_kiss_yaw=prev_kiss_yaw)
        if raw_pose is not None:
            last_raw_pose = raw_pose
        if gated:
            gated_count += 1
            continue
        if entry is None:
            continue

        prev_kiss_xy = (entry["x"], entry["y"])
        prev_kiss_yaw = entry["yaw"]
        if entry["map_paused"]:
            map_paused_count += 1

        frame_count += 1
        entry["frame"] = frame_count
        entry["gated_total"] = gated_count
        entry["map_paused_total"] = map_paused_count
        print(json.dumps(entry), flush=True)


def run_kiss_icp(dataset_path, voxel_size=0.15, max_range=12.0, min_range=0.35,
                  yaw_rate_gate=YAW_RATE_GATE_RAD):
    print(f"[KISS-ICP] Processing {dataset_path} (voxel_size={voxel_size}m, yaw_rate_gate={yaw_rate_gate})...")

    config = KISSConfig()
    config.mapping.voxel_size = voxel_size
    config.data.max_range = max_range
    config.data.min_range = min_range
    config.data.deskew = False

    odo = KissICP(config)

    trajectory = []
    map_voxels = {}

    t0 = time.time()
    frame_count = 0
    gated_count = 0
    map_paused_count = 0
    last_raw_pose = None
    jump_history = []
    prev_kiss_xy = None
    yaw_jump_history = []
    prev_kiss_yaw = None

    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            pts_raw = data.get("points", [])
            if not pts_raw:
                continue

            raw_pose = None
            if yaw_rate_gate is not None:
                raw_pose = (data.get("x") or 0.0, data.get("y") or 0.0, data.get("yaw") or 0.0)

            entry, gated = _register_and_accumulate(odo, map_voxels, pts_raw, min_range, max_range,
                                                      raw_pose=raw_pose, last_raw_pose=last_raw_pose,
                                                      yaw_rate_gate=yaw_rate_gate,
                                                      jump_history=jump_history, prev_kiss_xy=prev_kiss_xy,
                                                      yaw_jump_history=yaw_jump_history, prev_kiss_yaw=prev_kiss_yaw)
            if raw_pose is not None:
                last_raw_pose = raw_pose
            if gated:
                gated_count += 1
                continue
            if entry is None:
                continue

            prev_kiss_xy = (entry["x"], entry["y"])
            prev_kiss_yaw = entry["yaw"]
            if entry["map_paused"]:
                map_paused_count += 1

            x, y, z = entry["x"], entry["y"], entry["z"]
            trajectory.append(entry)
            frame_count += 1
            if frame_count % 100 == 0:
                print(f"  Processed {frame_count} frames... Current pos: ({x:.2f}, {y:.2f}, {z:.2f})")

    elapsed = time.time() - t0
    fps = frame_count / elapsed if elapsed > 0 else 0
    print(f"[KISS-ICP] Completed {frame_count} frames in {elapsed:.2f}s ({fps:.1f} FPS). "
          f"Gated (fast-spin, skipped): {gated_count}. Map paused (bad match, pose kept): "
          f"{map_paused_count}. Map voxels: {len(map_voxels)}")

    return trajectory, list(map_voxels.values())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        bridge_url = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:5003"
        run_kiss_icp_live(bridge_url)
    else:
        dataset = sys.argv[1] if len(sys.argv) > 1 else "docker/mapping/walk_kicsi.jsonl"
        no_gate = "--no-gate" in sys.argv
        traj, map_pts = run_kiss_icp(dataset, yaw_rate_gate=None if no_gate else YAW_RATE_GATE_RAD)
        print(f"Done. Trajectory points: {len(traj)}")
