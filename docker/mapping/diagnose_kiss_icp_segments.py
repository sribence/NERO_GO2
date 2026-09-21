"""
Szelet-diagnosztika: melyik időablakban romlik el a KISS-ICP illesztés az élő,
szabálytalan (akadálykerülő) felvételen.

Frame-enként regisztrál KISS-ICP-vel, és minden lépésnél feljegyzi:
  - nyers SDK roll/pitch/yaw (a robot dőlése/fordulása)
  - KISS-ICP saját pózváltozása (last_delta) -- ha ez hirtelen nagyot ugrik,
    az ICP elvesztette a illesztést az adott keretnél
  - kiss_icp saját adaptive_threshold-ja (a becsült zaj-szint; kiugrás =
    bizonytalan regisztráció)

Kimenet: konzol-táblázat + PNG-k a leggyanúsabb ablakokról (csak az adott
szelet pontjai, a szelet saját lokális KISS-ICP trajektóriájával rárajzolva)
-- így külön látszik, hogy egy adott szegmens önmagában jó térképet ad-e,
függetlenül a felvétel többi részének driftjétől.
"""
import json
import math
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from kiss_icp.kiss_icp import KissICP
from kiss_icp.config import KISSConfig


def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def load_frames(path):
    frames = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            frames.append(json.loads(line))
    return frames


def make_odo(voxel_size=0.15, max_range=12.0, min_range=0.35):
    config = KISSConfig()
    config.mapping.voxel_size = voxel_size
    config.data.max_range = max_range
    config.data.min_range = min_range
    config.data.deskew = False
    return KissICP(config), min_range, max_range


def register_all(frames):
    """Frame-enkénti regisztráció, per-frame diagnosztikai sorral."""
    odo, min_range, max_range = make_odo()
    rows = []
    last_raw = None
    prev_kiss_xy = None
    for i, fr in enumerate(frames):
        pts_raw = fr.get("points") or []
        pts = np.array(pts_raw, dtype=np.float64)[:, :3] if pts_raw else np.empty((0, 3))
        dist = np.hypot(pts[:, 0], pts[:, 1]) if len(pts) else np.array([])
        valid = (dist >= min_range) & (dist <= max_range) & (pts[:, 2] > -0.6) & (pts[:, 2] < 2.0) if len(pts) else np.array([], dtype=bool)
        vpts = pts[valid] if len(pts) else pts

        roll = fr.get("roll") or 0.0
        pitch = fr.get("pitch") or 0.0
        yaw = fr.get("yaw") or 0.0
        x_r = fr.get("x") or 0.0
        y_r = fr.get("y") or 0.0
        if last_raw is None:
            raw_yaw_rate = 0.0
            raw_step_m = 0.0
        else:
            raw_yaw_rate = abs(wrap_angle(yaw - last_raw[2]))
            raw_step_m = math.hypot(x_r - last_raw[0], y_r - last_raw[1])
        last_raw = (x_r, y_r, yaw)

        n_valid = len(vpts)
        if n_valid < 30:
            rows.append(dict(i=i, n_valid=n_valid, roll=roll, pitch=pitch,
                              raw_yaw_rate=raw_yaw_rate, raw_step_m=raw_step_m,
                              kiss_jump_m=None, adaptive_thresh=None,
                              kx=None, ky=None, skipped=True))
            continue

        ts = np.zeros(n_valid, dtype=np.float64)
        odo.register_frame(vpts, ts)
        pose = odo.last_pose
        kx, ky = float(pose[0, 3]), float(pose[1, 3])
        thresh = float(odo.adaptive_threshold.compute_threshold()) if hasattr(odo.adaptive_threshold, "compute_threshold") else None

        if prev_kiss_xy is None:
            kiss_jump_m = 0.0
        else:
            kiss_jump_m = math.hypot(kx - prev_kiss_xy[0], ky - prev_kiss_xy[1])
        prev_kiss_xy = (kx, ky)

        rows.append(dict(i=i, n_valid=n_valid, roll=roll, pitch=pitch,
                          raw_yaw_rate=raw_yaw_rate, raw_step_m=raw_step_m,
                          kiss_jump_m=kiss_jump_m, adaptive_thresh=thresh,
                          kx=kx, ky=ky, skipped=False))
    return rows


def print_table(rows):
    print(f"{'i':>4} {'valid':>6} {'roll':>7} {'pitch':>7} {'yaw_rate':>9} {'step_m':>7} {'kiss_jump_m':>12} {'thresh':>8}")
    jumps = [r["kiss_jump_m"] for r in rows if r["kiss_jump_m"] is not None]
    med_jump = float(np.median(jumps)) if jumps else 0.0
    flagged = []
    for r in rows:
        if r["skipped"]:
            print(f"{r['i']:>4} {r['n_valid']:>6} {r['roll']:>7.3f} {r['pitch']:>7.3f} {r['raw_yaw_rate']:>9.3f} {r['raw_step_m']:>7.3f} {'SKIP':>12} {'':>8}")
            continue
        anomaly = r["kiss_jump_m"] > max(0.15, med_jump * 4)
        mark = " <<<" if anomaly else ""
        if anomaly:
            flagged.append(r["i"])
        print(f"{r['i']:>4} {r['n_valid']:>6} {r['roll']:>7.3f} {r['pitch']:>7.3f} {r['raw_yaw_rate']:>9.3f} {r['raw_step_m']:>7.3f} {r['kiss_jump_m']:>12.3f} {(r['adaptive_thresh'] or 0):>8.3f}{mark}")
    print(f"\nMedián kiss_jump_m: {med_jump:.3f} | Gyanús keretek (>4x medián, min 0.15m): {flagged}")
    return flagged, med_jump


def plot_segment(frames, start, end, out_png, voxel_size=0.15, yaw_rate_gate=None):
    """Egy [start,end) szelet önálló KISS-ICP térképe és trajektóriája,
    a szelet SAJÁT első keretéhez viszonyítva (nem a teljes felvétel drift-jével).

    yaw_rate_gate=None: régi, gate nélküli viselkedés (minden keret regisztrálva).
    yaw_rate_gate=<rad>: run_kiss_icp.py fast-turn gate-je -- gyors fordulatú
    keretek kimaradnak a regisztrációból/térképből, csak a nyers SDK delta
    viszi tovább a pózt kezdő-becslésként a következő elfogadott keretig."""
    odo, min_range, max_range = make_odo(voxel_size=voxel_size)
    traj = []
    pts_all = []
    last_raw_pose = None
    n_gated = 0
    for fr in frames[start:end]:
        pts_raw = fr.get("points") or []
        raw_pose = (fr.get("x") or 0.0, fr.get("y") or 0.0, fr.get("yaw") or 0.0) if yaw_rate_gate is not None else None

        if raw_pose is not None and last_raw_pose is not None:
            dyaw = wrap_angle(raw_pose[2] - last_raw_pose[2])
            if abs(dyaw) >= yaw_rate_gate:
                dx, dy = raw_pose[0] - last_raw_pose[0], raw_pose[1] - last_raw_pose[1]
                c, s = math.cos(dyaw), math.sin(dyaw)
                T = np.eye(4, dtype=np.float64)
                T[0, 0], T[0, 1], T[1, 0], T[1, 1] = c, -s, s, c
                T[0, 3], T[1, 3] = dx, dy
                odo.last_pose = odo.last_pose @ T
                odo.last_delta = T
                last_raw_pose = raw_pose
                n_gated += 1
                continue
        if raw_pose is not None:
            last_raw_pose = raw_pose

        if not pts_raw:
            continue
        pts = np.array(pts_raw, dtype=np.float64)[:, :3]
        dist = np.hypot(pts[:, 0], pts[:, 1])
        valid = (dist >= min_range) & (dist <= max_range) & (pts[:, 2] > -0.6) & (pts[:, 2] < 2.0)
        vpts = pts[valid]
        if len(vpts) < 30:
            continue
        ts = np.zeros(len(vpts), dtype=np.float64)
        odo.register_frame(vpts, ts)
        pose = odo.last_pose
        R, t = pose[:3, :3], pose[:3, 3]
        world_pts = (vpts @ R.T) + t
        pts_all.append(world_pts[:, :2])
        traj.append((t[0], t[1]))

    if not pts_all:
        print(f"[{start}:{end}] nincs elég pont, kihagyva")
        return

    pts2d = np.concatenate(pts_all, axis=0)
    traj = np.array(traj)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(pts2d[:, 0], pts2d[:, 1], s=1, c="#4aa8ff", alpha=0.5)
    ax.plot(traj[:, 0], traj[:, 1], c="#2ecc71", linewidth=1.5, marker="o", markersize=2)
    ax.scatter([traj[0, 0]], [traj[0, 1]], c="yellow", s=80, zorder=5, label="start")
    ax.set_aspect("equal")
    gate_label = f", gate={yaw_rate_gate}rad, kihagyva={n_gated}" if yaw_rate_gate is not None else ", gate nélkül"
    ax.set_title(f"keret {start}:{end} (KISS-ICP{gate_label})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    print(f"mentve: {out_png} ({len(pts2d)} pont, {len(traj)} pózban, {n_gated} kihagyva)")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "walk_live_rect_2026-09-21_v2.jsonl"
    frames = load_frames(path)
    print(f"{len(frames)} keret betöltve: {path}\n")
    rows = register_all(frames)
    flagged, med_jump = print_table(rows)
