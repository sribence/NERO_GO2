"""
NERO GO2 — Small-GICP (VGICP) Pure LiDAR Odometry Pipeline
Runs modern Voxelized Generalized ICP on Hesai PandarXT-16 point clouds.
No wheel odometry required!
"""

import json
import math
import sys
import time
import numpy as np
import small_gicp

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

def run_small_gicp(dataset_path, voxel_size=0.15, max_range=12.0, min_range=0.35):
    print(f"[Small-GICP] Processing {dataset_path} (voxel_size={voxel_size}m)...")
    
    trajectory = []
    map_voxels = {}
    
    t0 = time.time()
    frame_count = 0
    
    T_world_curr = np.eye(4, dtype=np.float64)
    last_pts = None
    
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
                
            if last_pts is not None:
                # Align current frame to previous frame using VGICP
                result = small_gicp.align(
                    last_pts,
                    valid_pts,
                    np.eye(4, dtype=np.float64),
                    registration_type="VGICP",
                    voxel_resolution=voxel_size,
                    max_correspondence_distance=0.5,
                    max_iterations=20
                )
                dT = result.T_target_source
                T_world_curr = T_world_curr @ dT
            
            last_pts = valid_pts
            
            x, y, z = T_world_curr[:3, 3]
            roll, pitch, yaw = rotation_matrix_to_euler(T_world_curr[:3, :3])
            
            trajectory.append({
                "x": float(x),
                "y": float(y),
                "z": float(z),
                "roll": float(roll),
                "pitch": float(pitch),
                "yaw": float(wrap_angle(yaw))
            })
            
            # Accumulate into map voxel grid (2 cm resolution for map quality)
            R = T_world_curr[:3, :3]
            t_vec = T_world_curr[:3, 3]
            world_pts = (valid_pts @ R.T) + t_vec
            
            for p in world_pts[::3]:
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
    print(f"[Small-GICP] Completed {frame_count} frames in {elapsed:.2f}s ({fps:.1f} FPS). Map voxels: {len(map_voxels)}")
    
    return trajectory, list(map_voxels.values())

if __name__ == "__main__":
    dataset = sys.argv[1] if len(sys.argv) > 1 else "docker/mapping/walk_kicsi.jsonl"
    traj, map_pts = run_small_gicp(dataset)
    print(f"Done. Trajectory points: {len(traj)}")
