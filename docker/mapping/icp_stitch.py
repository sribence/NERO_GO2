"""
NERO_GO2 szegmens-összefűzés ICP scan-matching-gel.

Az eddigi build_map.py egyben, a teljes séta abszolút (SportModeState_
odometria) pozíciójára támaszkodva rakta világ-koordinátákba a pontokat —
ez rövid/lokális szegmenseken (10-15 mp) jól működött, de a teljes,
összetett útvonalon (folyosóra is kimenve) az odometria driftje szétkente
a térképet.

Ez a script helyette:
  1. Felszeleteli a felvételt fix idejű (alapértelmezetten 10 mp-es)
     szegmensekre.
  2. Minden szegmensből egy LOKÁLIS pontfelhőt épít — a szegmens ELSŐ
     keretéhez relatív pozícióval/yaw-val (nem az abszolút, driftelő
     világ-koordinátával). Rövid (10 mp-es) ablakon belül a drift
     elhanyagolható, ez volt a mai este bizonyított állítás.
  3. Az odometriát csak KEZDETI BECSLÉSKÉNT használja a szegmensek egymáshoz
     illesztéséhez — a végső illesztést egy saját 2D point-to-point ICP
     (Iterative Closest Point) számolja a tényleges pontfelhők alapján.
  4. Az ICP-lánc mentén minden szegmenst a globális térképbe helyez, és
     kiírja mindegyik lépésnél, mennyit korrigált az odometria becsléséhez
     képest — ez a kért "teszt-log".

Nem open3d-t használ (nem telepített, nagy függőség lenne) — egy saját,
könnyű 2D ICP implementáció numpy + scipy.spatial.cKDTree-vel, ami
pontosan ugyanazt az elvet követi (legközelebbi-pont párosítás + optimális
merevtest-transzformáció SVD-vel, iterálva).
"""

import argparse
import json

import cv2
import numpy as np
from scipy.spatial import cKDTree

Z_BAND_HALF = 0.05
MIN_RANGE_M = 0.5
MAX_RANGE_M = 5.0
MAX_TILT_RAD = 0.30
SEGMENT_SECONDS = 10.0
HZ_ASSUMED = 8.0  # a data_logger.py alap mintavételi rátája

ICP_MAX_ITERS = 40
ICP_MAX_CORR_DIST = 0.25  # méter — ennél távolabbi legközelebbi-szomszéd párt kizárjuk
ICP_MIN_MATCHES = 30
ICP_CONVERGE_TOL = 1e-5


def load_frames(path):
    frames = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                frames.append(json.loads(line))
    return frames


def tilt_compensated_local_xy(frame):
    """Egy keret pontfelhőjét visszaadja a SZENZOR saját (nem világ-)
    koordinátáiban, roll/pitch-kompenzálva, Z-vágva, táv-szűrve — ugyanaz a
    logika, mint build_map.py-ban, csak itt NEM forgatjuk/toljuk el yaw-val
    és pozícióval, azt a hívó végzi (relatív pózhoz)."""
    pts = frame.get("points") or []
    if not pts:
        return np.empty((0, 2))
    arr = np.asarray(pts, dtype=np.float64)
    if arr.shape[0] == 0:
        return np.empty((0, 2))

    roll = frame.get("roll") or 0.0
    pitch = frame.get("pitch") or 0.0
    if abs(roll) > MAX_TILT_RAD or abs(pitch) > MAX_TILT_RAD:
        return np.empty((0, 2))

    xyz = arr[:, :3].copy()
    if roll or pitch:
        cr, sr = np.cos(-roll), np.sin(-roll)
        cp, sp = np.cos(-pitch), np.sin(-pitch)
        rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
        ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
        xyz = xyz @ rx.T @ ry.T

    z_mask = np.abs(xyz[:, 2]) <= Z_BAND_HALF
    xyz = xyz[z_mask]
    if xyz.shape[0] == 0:
        return np.empty((0, 2))

    dist = np.hypot(xyz[:, 0], xyz[:, 1])
    range_mask = (dist >= MIN_RANGE_M) & (dist <= MAX_RANGE_M)
    xyz = xyz[range_mask]
    return xyz[:, :2]


def relative_pose(frame, ref_x, ref_y, ref_yaw):
    """A frame póza a (ref_x, ref_y, ref_yaw) referenciakerethez képest."""
    dx_world = (frame.get("x") or 0.0) - ref_x
    dy_world = (frame.get("y") or 0.0) - ref_y
    cos_r, sin_r = np.cos(-ref_yaw), np.sin(-ref_yaw)
    local_dx = dx_world * cos_r - dy_world * sin_r
    local_dy = dx_world * sin_r + dy_world * cos_r
    local_yaw = (frame.get("yaw") or 0.0) - ref_yaw
    # Szög-normalizálás [-pi, pi]-be -- a nyers kivonás a -180/+180-as
    # határátmenetnél (pl. yaw=+179 -> -179) egy majdnem 360 fokos hamis
    # ugrást adna, ami irreális "odometria becslést" okoz az ICP-nek.
    local_yaw = (local_yaw + np.pi) % (2 * np.pi) - np.pi
    return local_dx, local_dy, local_yaw


def segment_point_cloud(frames_segment):
    """A szegmens ELSŐ keretéhez relatív, lokális pontfelhő — a szegmensen
    belüli (rövid idejű, elhanyagolható driftű) odometriát használva."""
    if not frames_segment or frames_segment[0].get("x") is None:
        return np.empty((0, 2)), (0.0, 0.0, 0.0)

    ref_x = frames_segment[0]["x"]
    ref_y = frames_segment[0]["y"]
    ref_yaw = frames_segment[0]["yaw"]

    all_pts = []
    for frame in frames_segment:
        local_xy = tilt_compensated_local_xy(frame)
        if local_xy.shape[0] == 0:
            continue
        dx, dy, dyaw = relative_pose(frame, ref_x, ref_y, ref_yaw)
        cos_y, sin_y = np.cos(dyaw), np.sin(dyaw)
        rot = np.array([[cos_y, -sin_y], [sin_y, cos_y]])
        world = local_xy @ rot.T
        world[:, 0] += dx
        world[:, 1] += dy
        all_pts.append(world)

    if not all_pts:
        return np.empty((0, 2)), (ref_x, ref_y, ref_yaw)
    return np.concatenate(all_pts, axis=0), (ref_x, ref_y, ref_yaw)


def best_rigid_transform_2d(src, dst):
    """Kabsch-algoritmus 2D-ben: az a (R, t) merevtest-transzformáció, ami
    minimalizálja sum(|R@src_i + t - dst_i|^2)-t. src/dst: (N,2) párosított pontok."""
    centroid_src = src.mean(axis=0)
    centroid_dst = dst.mean(axis=0)
    src_c = src - centroid_src
    dst_c = dst - centroid_dst
    H = src_c.T @ dst_c
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:  # tükrözés-javítás
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    t = centroid_dst - R @ centroid_src
    return R, t


def icp_2d(src_points, dst_points, init_R, init_t, log_prefix=""):
    """Pont-pont ICP: src_points-et illeszti dst_points-ra, init_R/init_t
    kezdeti becslésből indulva. Visszaadja a végső (R, t)-t és a
    konvergencia-logot (lista stringekkel, kiírható a felhasználónak)."""
    tree = cKDTree(dst_points)
    R, t = init_R.copy(), init_t.copy()
    log_lines = []

    for it in range(ICP_MAX_ITERS):
        transformed = (R @ src_points.T).T + t
        distances, indices = tree.query(transformed)
        mask = distances < ICP_MAX_CORR_DIST
        n_matches = int(mask.sum())
        if n_matches < ICP_MIN_MATCHES:
            log_lines.append(f"{log_prefix}iter {it}: csak {n_matches} párosítás (<{ICP_MIN_MATCHES}) — leállás")
            break

        matched_src = src_points[mask]
        matched_dst = dst_points[indices[mask]]
        new_R, new_t = best_rigid_transform_2d(matched_src, matched_dst)

        delta = np.linalg.norm(new_R - R) + np.linalg.norm(new_t - t)
        mean_dist = float(distances[mask].mean())
        log_lines.append(
            f"{log_prefix}iter {it:2d}: {n_matches:4d} párosítás, átlagos hiba={mean_dist:.4f}m, delta={delta:.6f}"
        )
        R, t = new_R, new_t
        if delta < ICP_CONVERGE_TOL:
            log_lines.append(f"{log_prefix}konvergált ({it+1} iteráció után)")
            break

    return R, t, log_lines


def yaw_from_R(R):
    return float(np.arctan2(R[1, 0], R[0, 0]))


def main():
    ap = argparse.ArgumentParser(description="Szegmens-összefűzés ICP scan-matching-gel.")
    ap.add_argument("input", help="a data_logger.py-vel mentett .jsonl fájl")
    ap.add_argument("--segment-seconds", type=float, default=SEGMENT_SECONDS)
    ap.add_argument("--resolution", type=float, default=0.05)
    ap.add_argument("--out-png", default=None)
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args()

    out_png = args.out_png or (args.input.rsplit(".", 1)[0] + ".icp.png")
    out_json = args.out_json or (args.input.rsplit(".", 1)[0] + ".icp.json")

    frames = load_frames(args.input)
    win = int(args.segment_seconds * HZ_ASSUMED)
    segments = [frames[i:i + win] for i in range(0, len(frames), win) if len(frames[i:i + win]) >= win // 2]
    print(f"{len(frames)} keret -> {len(segments)} szegmens ({args.segment_seconds}s / szegmens)")

    # Minden szegmens lokális pontfelhője + a szegmens referenciapózja
    # (az odometria adta, EREDETI, driftes abszolút póz -- ez adja a kezdeti becslést).
    seg_clouds = []
    seg_ref_poses = []
    for seg in segments:
        cloud, ref_pose = segment_point_cloud(seg)
        seg_clouds.append(cloud)
        seg_ref_poses.append(ref_pose)

    # Globális pózok: a 0. szegmenst rögzítjük (R=I, t=0 a saját referenciapózához
    # képest), minden további szegmenst az ELŐZŐHÖZ ICP-vel illesztünk, és
    # láncoljuk a transzformációkat a globális kerethez.
    global_R = [np.eye(2)]
    global_t = [np.zeros(2)]

    print()
    print("=== ICP illesztési log (szegmens N -> N+1) ===")
    for i in range(1, len(segments)):
        prev_cloud, cur_cloud = seg_clouds[i - 1], seg_clouds[i]
        if prev_cloud.shape[0] < ICP_MIN_MATCHES or cur_cloud.shape[0] < ICP_MIN_MATCHES:
            print(f"[{i-1}->{i}] túl kevés pont, odometria-becslés marad")
            init_R = np.eye(2)
            ref_prev = seg_ref_poses[i - 1]
            ref_cur = seg_ref_poses[i]
            dx, dy, dyaw = relative_pose({"x": ref_cur[0], "y": ref_cur[1], "yaw": ref_cur[2]}, *ref_prev)
            init_t = np.array([dx, dy])
            R_step, t_step = np.array([[np.cos(dyaw), -np.sin(dyaw)], [np.sin(dyaw), np.cos(dyaw)]]), init_t
        else:
            # Kezdeti becslés az odometriából: a szegmens i referenciapózának
            # relatív helyzete a szegmens i-1 referenciapózához képest.
            ref_prev = seg_ref_poses[i - 1]
            ref_cur = seg_ref_poses[i]
            dx, dy, dyaw = relative_pose({"x": ref_cur[0], "y": ref_cur[1], "yaw": ref_cur[2]}, *ref_prev)
            init_R = np.array([[np.cos(dyaw), -np.sin(dyaw)], [np.sin(dyaw), np.cos(dyaw)]])
            init_t = np.array([dx, dy])

            R_step, t_step, log_lines = icp_2d(cur_cloud, prev_cloud, init_R, init_t, log_prefix=f"  [{i-1}->{i}] ")
            for line in log_lines:
                print(line)

            odom_yaw_deg = np.degrees(dyaw)
            icp_yaw_deg = np.degrees(yaw_from_R(R_step))
            print(
                f"[{i-1}->{i}] odometria becslés: dx={dx:+.3f} dy={dy:+.3f} dyaw={odom_yaw_deg:+.1f}°  |  "
                f"ICP finomítás: dx={t_step[0]:+.3f} dy={t_step[1]:+.3f} dyaw={icp_yaw_deg:+.1f}°  "
                f"(korrekció: {np.hypot(t_step[0]-dx, t_step[1]-dy):.3f}m, {icp_yaw_deg-odom_yaw_deg:+.1f}°)"
            )

        # Lánc: globális_R[i] = globális_R[i-1] @ R_step, globális_t[i] = globális_R[i-1]@t_step + globális_t[i-1]
        global_R.append(global_R[i - 1] @ R_step)
        global_t.append(global_R[i - 1] @ t_step + global_t[i - 1])

    # Minden szegmens pontfelhőjét a globális kerembe helyezzük, és
    # összeépítjük az occupancy grid térképet -- ugyanaz a rács-logika,
    # mint build_map.py-ban.
    all_world_pts = []
    all_ref_world = []
    for i, cloud in enumerate(seg_clouds):
        if cloud.shape[0] == 0:
            continue
        world = (global_R[i] @ cloud.T).T + global_t[i]
        all_world_pts.append(world)
        all_ref_world.append(global_t[i])

    if not all_world_pts:
        print("Nincs elég pont a végleges térképhez.")
        return

    pts = np.concatenate(all_world_pts, axis=0)
    refs = np.array(all_ref_world)
    all_xy = np.concatenate([pts, refs], axis=0)
    min_x, min_y = all_xy.min(axis=0) - 1.0
    max_x, max_y = all_xy.max(axis=0) + 1.0
    resolution = args.resolution
    width = max(10, int(np.ceil((max_x - min_x) / resolution)))
    height = max(10, int(np.ceil((max_y - min_y) / resolution)))
    print(f"\nVégső rács: {width}x{height} cella ({resolution}m/cella)")

    grid = np.full((height, width), -1, dtype=np.int16)
    free_mask = np.zeros((height, width), dtype=np.uint8)

    def to_cell(wx, wy):
        return int((wx - min_x) / resolution), int((wy - min_y) / resolution)

    for i, cloud in enumerate(seg_clouds):
        if cloud.shape[0] == 0:
            continue
        world = (global_R[i] @ cloud.T).T + global_t[i]
        rcx, rcy = to_cell(*global_t[i])
        step = max(1, world.shape[0] // 1500)
        for wx, wy in world[::step]:
            pcx, pcy = to_cell(wx, wy)
            cv2.line(free_mask, (rcx, rcy), (pcx, pcy), color=1, thickness=1)

    grid[free_mask == 1] = 0

    OCCUPIED_HIT_THRESHOLD = 3
    hit_counts = np.zeros((height, width), dtype=np.int32)
    cell_xy = np.floor((pts - np.array([min_x, min_y])) / resolution).astype(np.int32)
    valid = (cell_xy[:, 0] >= 0) & (cell_xy[:, 0] < width) & (cell_xy[:, 1] >= 0) & (cell_xy[:, 1] < height)
    cell_xy = cell_xy[valid]
    np.add.at(hit_counts, (cell_xy[:, 1], cell_xy[:, 0]), 1)
    grid[hit_counts >= OCCUPIED_HIT_THRESHOLD] = 100

    n_free = int((grid == 0).sum())
    n_occ = int((grid == 100).sum())
    n_unknown = int((grid == -1).sum())
    print(f"  szabad: {n_free}, akadály: {n_occ}, ismeretlen: {n_unknown}")

    img = np.zeros(grid.shape, dtype=np.uint8)
    img[grid == -1] = 120
    img[grid == 0] = 255
    img[grid == 100] = 0
    img = np.flipud(img)
    cv2.imwrite(out_png, img)

    payload = {
        "width": width, "height": height, "resolution": resolution,
        "origin_x": float(min_x), "origin_y": float(min_y),
        "data": grid.astype(np.int16).flatten().tolist(),
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print(f"Mentve: {out_png}, {out_json}")


if __name__ == "__main__":
    main()
