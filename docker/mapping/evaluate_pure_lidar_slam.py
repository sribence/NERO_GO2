"""
NERO GO2 — Pure LiDAR Odometry Benchmark & Quality Evaluator
Compares:
1. Raw Corrected Odometry (0.99x gyro, 96.0deg offset)
2. KISS-ICP (PRBonn Pure LiDAR Odometry)
3. Small-GICP (VGICP Pure LiDAR Odometry)
"""

import json
import math
import sys
import time
import numpy as np
from scipy.spatial import cKDTree

from kiss_icp.kiss_icp import KissICP
from kiss_icp.config import KISSConfig
import small_gicp

def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi

def evaluate_pure_lidar(dataset_path):
    print(f"=== Evaluating Pure LiDAR Odometry on {dataset_path} ===")
    
    raw_lines = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            raw_lines.append(json.loads(line))
            
    print(f"Total raw dataset frames: {len(raw_lines)}")
    
    # 1. Raw Corrected Odometry Trajectory
    yaw_scale = 0.99
    yaw_offset = math.radians(96.0)
    
    raw_traj = []
    last_raw = None
    curr_x, curr_y, curr_yaw = 0.0, 0.0, 0.0
    
    for fr in raw_lines:
        x_r = float(fr.get("x", 0) or 0.0)
        y_r = float(fr.get("y", 0) or 0.0)
        yaw_r = float(wrap_angle((fr.get("yaw", 0) or 0.0) * yaw_scale + yaw_offset))
        
        if last_raw is None:
            curr_x, curr_y, curr_yaw = x_r, y_r, yaw_r
        else:
            dx = x_r - last_raw[0]
            dy = y_r - last_raw[1]
            dyaw = wrap_angle(yaw_r - last_raw[2])
            
            cosP = math.cos(last_raw[2])
            sinP = math.sin(last_raw[2])
            dx_b = cosP * dx + sinP * dy
            dy_b = -sinP * dx + cosP * dy
            
            curr_x += math.cos(curr_yaw) * dx_b - math.sin(curr_yaw) * dy_b
            curr_y += math.sin(curr_yaw) * dx_b + math.cos(curr_yaw) * dy_b
            curr_yaw = wrap_angle(curr_yaw + dyaw)
            
        last_raw = (x_r, y_r, yaw_r)
        raw_traj.append((curr_x, curr_y, curr_yaw))

    # 2. KISS-ICP Pure LiDAR Trajectory
    t0_kiss = time.time()
    config = KISSConfig()
    config.mapping.voxel_size = 0.15
    config.data.max_range = 12.0
    config.data.min_range = 0.35
    config.data.deskew = False
    kiss_odo = KissICP(config)
    kiss_traj = []
    
    for fr in raw_lines:
        pts = np.array(fr.get("points", []), dtype=np.float64)[:, :3]
        dist = np.hypot(pts[:, 0], pts[:, 1])
        valid = (dist >= 0.35) & (dist <= 12.0) & (pts[:, 2] > -0.6) & (pts[:, 2] < 2.0)
        vpts = pts[valid]
        if len(vpts) < 30:
            kiss_traj.append(kiss_traj[-1] if kiss_traj else (0.0, 0.0, 0.0))
            continue
        ts = np.zeros(len(vpts), dtype=np.float64)
        kiss_odo.register_frame(vpts, ts)
        kp = kiss_odo.last_pose
        kx, ky = float(kp[0, 3]), float(kp[1, 3])
        kyaw = float(wrap_angle(math.atan2(kp[1, 0], kp[0, 0])))
        kiss_traj.append((kx, ky, kyaw))
    kiss_fps = len(raw_lines) / (time.time() - t0_kiss)

    # 3. Small-GICP Pure LiDAR Trajectory
    t0_gicp = time.time()
    gicp_traj = []
    T_gicp = np.eye(4, dtype=np.float64)
    last_vpts = None
    
    for fr in raw_lines:
        pts = np.array(fr.get("points", []), dtype=np.float64)[:, :3]
        dist = np.hypot(pts[:, 0], pts[:, 1])
        valid = (dist >= 0.35) & (dist <= 12.0) & (pts[:, 2] > -0.6) & (pts[:, 2] < 2.0)
        vpts = pts[valid]
        if len(vpts) < 30:
            gicp_traj.append(gicp_traj[-1] if gicp_traj else (0.0, 0.0, 0.0))
            continue
        if last_vpts is not None:
            res = small_gicp.align(
                last_vpts,
                vpts,
                np.eye(4, dtype=np.float64),
                registration_type="VGICP",
                voxel_resolution=0.15,
                max_correspondence_distance=0.5,
                max_iterations=20
            )
            T_gicp = T_gicp @ res.T_target_source
        last_vpts = vpts
        gx, gy = float(T_gicp[0, 3]), float(T_gicp[1, 3])
        gyaw = float(wrap_angle(math.atan2(T_gicp[1, 0], T_gicp[0, 0])))
        gicp_traj.append((gx, gy, gyaw))
    gicp_fps = len(raw_lines) / (time.time() - t0_gicp)

    def measure_map_quality(traj):
        map_voxels = set()
        wall_pts = []
        for idx, fr in enumerate(raw_lines[::2]):
            pose = traj[idx * 2] if (idx * 2) < len(traj) else traj[-1]
            pts = np.array(fr.get("points", []), dtype=np.float32)[:, :3]
            if len(pts) == 0: continue
            dist = np.hypot(pts[:, 0], pts[:, 1])
            valid = (dist > 0.35) & (dist < 8.0) & (pts[:, 2] > -0.20)
            vpts = pts[valid]
            
            cy, sy = math.cos(pose[2]), math.sin(pose[2])
            rot = np.array([[cy, -sy], [sy, cy]], dtype=np.float32)
            pts_w = vpts[:, :2] @ rot.T + np.array([pose[0], pose[1]], dtype=np.float32)
            
            for p in pts_w:
                vx = int(round(p[0] / 0.03))
                vy = int(round(p[1] / 0.03))
                map_voxels.add((vx, vy))
                wall_pts.append(p)
                
        wall_arr = np.array(wall_pts, dtype=np.float32)
        if len(wall_arr) > 100:
            tree = cKDTree(wall_arr[::5])
            dists, _ = tree.query(wall_arr[::5], k=5)
            rms_disp = np.mean(np.std(dists[:, 1:], axis=1)) * 100.0
        else:
            rms_disp = 0.0
            
        return len(map_voxels), rms_disp

    vox_raw, rms_raw = measure_map_quality(raw_traj)
    vox_kiss, rms_kiss = measure_map_quality(kiss_traj)
    vox_gicp, rms_gicp = measure_map_quality(gicp_traj)

    print("\n--- RESULTS & METRICS ---")
    print(f"1. Raw Corrected Odometry (0.99x, 96.0°): {vox_raw:,} 3cm-voxels | Wall RMS: {rms_raw:.2f} cm")
    print(f"2. KISS-ICP Pure LiDAR:                   {vox_kiss:,} 3cm-voxels | Wall RMS: {rms_kiss:.2f} cm | Speed: {kiss_fps:.1f} FPS")
    print(f"3. Small-GICP Pure LiDAR:                 {vox_gicp:,} 3cm-voxels | Wall RMS: {rms_gicp:.2f} cm | Speed: {gicp_fps:.1f} FPS")

if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "docker/mapping/walk_kicsi.jsonl"
    evaluate_pure_lidar(ds)
