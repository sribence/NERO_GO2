"""Realtime elo terkep-nezet: menet kozben frissiti a PNG-t + auto-reload HTML-t.
Ctrl+C-ig fut (vagy DURATION_S masodpercig ha megadva)."""
import json
import sys
import time
import urllib.error
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, ".")
from run_kiss_icp import (_register_and_accumulate, deskew_points,
                           YAW_RATE_GATE_RAD)
from kiss_icp.kiss_icp import KissICP
from kiss_icp.config import KISSConfig

BRIDGE = "http://127.0.0.1:15003"
MOTION = "http://127.0.0.1:19102"
DASHBOARD = "http://127.0.0.1:15002"
DURATION_S = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0  # 0 = vegtelen
OUT_PREFIX = sys.argv[2] if len(sys.argv) > 2 else "live"
REDRAW_EVERY_S = 1.0

config = KISSConfig()
config.mapping.voxel_size = 0.15
config.data.max_range = 12.0
config.data.min_range = 0.35
config.data.deskew = False
odo = KissICP(config)

map_voxels = {}
jump_history = []
prev_kiss_xy = None
yaw_jump_history = []
prev_kiss_yaw = None
last_raw_pose = None
last_packet_count = -1
trajectory = []
last_redraw = 0.0

html_path = f"{OUT_PREFIX}.html"
with open(html_path, "w", encoding="utf-8") as f:
    f.write(
        f'<meta http-equiv="refresh" content="2">'
        f'<body style="margin:0;background:#111">'
        f'<img src="{OUT_PREFIX}.png?t={int(time.time())}" style="width:100%">'
        f'</body>'
    )
print(f"[live] nyisd meg: {html_path}", flush=True)


def redraw():
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    ax = axes[0]
    ok_pts = [(e["x"], e["y"]) for e in trajectory if not e["gated"] and not e["map_paused"]]
    paused_pts = [(e["x"], e["y"]) for e in trajectory if not e["gated"] and e["map_paused"]]
    if ok_pts:
        xs, ys = zip(*ok_pts)
        ax.plot(xs, ys, "-", c="#2ecc71", linewidth=1, alpha=0.6, zorder=1)
        ax.scatter(xs, ys, c="#2ecc71", s=12, label=f"normal ({len(ok_pts)})", zorder=3)
    if paused_pts:
        xs, ys = zip(*paused_pts)
        ax.scatter(xs, ys, c="#e74c3c", s=30, marker="x", label=f"gate ({len(paused_pts)})", zorder=4)
    if ok_pts:
        ax.scatter([ok_pts[0][0]], [ok_pts[0][1]], c="yellow", s=100, zorder=5,
                   edgecolors="black", label="start")
    ax.set_aspect("equal")
    n_gated = sum(1 for e in trajectory if e["gated"])
    ax.set_title(f"Trajectory (frame {len(trajectory)}, {n_gated} gated)")
    ax.legend(fontsize=8)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")

    ax2 = axes[1]
    if map_voxels:
        pts = np.array(list(map_voxels.values()))
        ax2.scatter(pts[:, 0], pts[:, 1], s=0.5, c=pts[:, 2], cmap="viridis", alpha=0.6)
        if ok_pts:
            xs, ys = zip(*ok_pts)
            ax2.plot(xs, ys, "-", c="red", linewidth=1.2, alpha=0.8)
    ax2.set_aspect("equal")
    ax2.set_title(f"Voxel map ({len(map_voxels)} pts) -- {time.strftime('%H:%M:%S')}")
    ax2.set_xlabel("x (m)")
    ax2.set_ylabel("y (m)")

    fig.tight_layout()
    fig.savefig(f"{OUT_PREFIX}.png", dpi=110)
    plt.close(fig)


t_end = time.time() + DURATION_S if DURATION_S > 0 else None
print("[live] recording... Ctrl+C to stop", flush=True)

try:
    while t_end is None or time.time() < t_end:
        try:
            with urllib.request.urlopen(f"{BRIDGE}/health", timeout=2.0) as resp:
                health = json.loads(resp.read())
        except Exception as e:
            print(f"[live] bridge unreachable ({e})", flush=True)
            time.sleep(0.3)
            continue

        packet_count = health.get("packet_count", 0)
        if not health.get("connected") or packet_count == last_packet_count:
            time.sleep(0.05)
            continue
        last_packet_count = packet_count

        try:
            with urllib.request.urlopen(f"{BRIDGE}/lidar", timeout=2.0) as resp:
                pts_raw = json.loads(resp.read())
        except Exception as e:
            print(f"[live] /lidar failed ({e})", flush=True)
            time.sleep(0.05)
            continue
        if not pts_raw:
            continue

        try:
            with urllib.request.urlopen(f"{MOTION}/imu/yaw_history", timeout=1.0) as resp:
                yh = json.loads(resp.read())
            yaw_samples = [(s["t"], s["yaw"]) for s in yh.get("samples", [])]
        except Exception:
            yaw_samples = []
        pts_raw = deskew_points(pts_raw, yaw_samples)

        raw_pose = None
        try:
            with urllib.request.urlopen(f"{DASHBOARD}/pose_snapshot", timeout=1.0) as resp:
                p = json.loads(resp.read())
            raw_pose = (p.get("position_x") or 0.0, p.get("position_y") or 0.0, p.get("yaw") or 0.0)
        except Exception:
            pass

        entry, gated = _register_and_accumulate(
            odo, map_voxels, pts_raw, 0.35, 12.0,
            raw_pose=raw_pose, last_raw_pose=last_raw_pose,
            yaw_rate_gate=YAW_RATE_GATE_RAD,
            jump_history=jump_history, prev_kiss_xy=prev_kiss_xy,
            yaw_jump_history=yaw_jump_history, prev_kiss_yaw=prev_kiss_yaw)
        if raw_pose is not None:
            last_raw_pose = raw_pose
        if gated:
            trajectory.append({"x": None, "y": None, "gated": True, "map_paused": False})
        elif entry is not None:
            prev_kiss_xy = (entry["x"], entry["y"])
            prev_kiss_yaw = entry["yaw"]
            entry["gated"] = False
            trajectory.append(entry)

        now = time.time()
        if now - last_redraw >= REDRAW_EVERY_S:
            redraw()
            last_redraw = now
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(
                    f'<meta http-equiv="refresh" content="2">'
                    f'<body style="margin:0;background:#111">'
                    f'<img src="{OUT_PREFIX}.png?t={int(now)}" style="width:100%">'
                    f'</body>'
                )
except KeyboardInterrupt:
    pass

redraw()
n_gated = sum(1 for e in trajectory if e["gated"])
n_paused = sum(1 for e in trajectory if not e["gated"] and e["map_paused"])
n_ok = sum(1 for e in trajectory if not e["gated"] and not e["map_paused"])
print(f"[live] done: {len(trajectory)} entries (ok={n_ok} paused={n_paused} gated={n_gated}), "
      f"{len(map_voxels)} voxels", flush=True)
