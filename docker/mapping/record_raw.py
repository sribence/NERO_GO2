"""Nyers mozgas-adatfolyam rogzitese jsonl-be, kesobbi robot nelkuli offline
teszthez. Ugyanaz a formatum mint run_kiss_icp()'s offline reader-e olvas
("points","x","y","yaw"), plusz "yaw_samples" es "t" extra mezovel.

Hasznalat: python record_raw.py <nev> <idotartam_s>
Kimenet: <nev>.jsonl a mapping/ mappaba."""
import json
import sys
import time
import urllib.error
import urllib.request

BRIDGE = "http://127.0.0.1:15003"
MOTION = "http://127.0.0.1:19102"
DASHBOARD = "http://127.0.0.1:15002"

NAME = sys.argv[1] if len(sys.argv) > 1 else "run"
DURATION_S = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
OUT = f"{NAME}.jsonl"

last_packet_count = -1
n_frames = 0
t_end = time.time() + DURATION_S
print(f"[record] '{NAME}' -- {DURATION_S:.0f}s, kimenet: {OUT}", flush=True)

with open(OUT, "w", encoding="utf-8") as out:
    while time.time() < t_end:
        try:
            with urllib.request.urlopen(f"{BRIDGE}/health", timeout=2.0) as resp:
                health = json.loads(resp.read())
        except Exception as e:
            print(f"[record] bridge unreachable ({e})", flush=True)
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
            print(f"[record] /lidar failed ({e})", flush=True)
            time.sleep(0.05)
            continue
        if not pts_raw:
            continue

        try:
            with urllib.request.urlopen(f"{MOTION}/imu/yaw_history", timeout=1.0) as resp:
                yh = json.loads(resp.read())
            yaw_samples = [[s["t"], s["yaw"]] for s in yh.get("samples", [])]
        except Exception:
            yaw_samples = []

        x = y = yaw = 0.0
        try:
            with urllib.request.urlopen(f"{DASHBOARD}/pose_snapshot", timeout=1.0) as resp:
                p = json.loads(resp.read())
            x = p.get("position_x") or 0.0
            y = p.get("position_y") or 0.0
            yaw = p.get("yaw") or 0.0
        except Exception:
            pass

        out.write(json.dumps({
            "t": time.time(),
            "points": pts_raw,
            "x": x, "y": y, "yaw": yaw,
            "yaw_samples": yaw_samples,
        }) + "\n")
        n_frames += 1
        if n_frames % 20 == 0:
            print(f"[record] {n_frames} keret rogzitve...", flush=True)

print(f"[record] kesz: {n_frames} keret -> {OUT}", flush=True)
