"""
NERO GO2 — KISS-ICP Pure LiDAR Odometry Pipeline
Runs KISS-ICP on raw Hesai PandarXT-16 point clouds from jsonl datasets.
No wheel odometry required!
"""

import json
import math
import sys
import time
import numpy as np

from kiss_icp.kiss_icp import KissICP
from kiss_icp.config import KISSConfig

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

def run_kiss_icp(dataset_path, voxel_size=0.15, max_range=12.0, min_range=0.35):
    print(f"[KISS-ICP] Processing {dataset_path} (voxel_size={voxel_size}m)...")
    
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
    
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            pts_raw = data.get("points", [])
            if not pts_raw:
                continue
                
            pts = np.array(pts_raw, dtype=np.float64)[:, :3]
            
            # Filter range
            dist = np.hypot(pts[:, 0], pts[:, 1])
            valid = (dist >= min_range) & (dist <= max_range) & (pts[:, 2] > -0.6) & (pts[:, 2] < 2.0)
            valid_pts = pts[valid]
            
            if len(valid_pts) < 50:
                continue
                
            ts = np.zeros(len(valid_pts), dtype=np.float64)
            odo.register_frame(valid_pts, ts)
            
            pose = odo.last_pose
            x, y, z = pose[:3, 3]
            roll, pitch, yaw = rotation_matrix_to_euler(pose[:3, :3])
            
            trajectory.append({
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "roll": float(roll),
                "pitch": float(pitch),
                "yaw": float(wrap_angle(yaw))
            })
            
            # Accumulate into map voxel grid (2 cm resolution for map quality)
            R = pose[:3, :3]
            t_vec = pose[:3, 3]
            world_pts = (valid_pts @ R.T) + t_vec
            
            for p in world_pts[::3]:  # Subsample for voxel map
                vx = int(math.floor(p[0] / 0.02))
                vy = int(math.floor(p[1] / 0.02))
                vz = int(math.floor(p[2] / 0.02))
                key = (vx, vy, vz)
                if key not in map_voxels:
                    map_voxels[key] = p.tolist()
            
            frame_count += 1
            if frame_count % 100 == 0:
                print(f"  Processed {frame_count} frames... Current pos: ({x:.2f}, {y:.2f}, {z:.2f})")
                
    elapsed = time.time() - t0
    fps = frame_count / elapsed if elapsed > 0 else 0
    print(f"[KISS-ICP] Completed {frame_count} frames in {elapsed:.2f}s ({fps:.1f} FPS). Map voxels: {len(map_voxels)}")
    
    return trajectory, list(map_voxels.values())

if __name__ == "__main__":
    dataset = sys.argv[1] if len(sys.argv) > 1 else "docker/mapping/walk_kicsi.jsonl"
    traj, map_pts = run_kiss_icp(dataset)
    print(f"Done. Trajectory points: {len(traj)}")
