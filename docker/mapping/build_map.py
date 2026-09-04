"""
NERO_GO2 saját (ROS-mentes) occupancy grid térképépítő — offline, a
data_logger.py-vel rögzített .jsonl felvételen dolgozik.

Tervezési döntések (mérnöki tanácsok alapján, ld. beszélgetés):
  - Vektorizált numpy (nincs Python for-ciklus pontonként) — a forgatás/
    eltolás mátrix-műveletekkel megy, több tízezer ponton is gyors.
  - cv2.line() a szabad terület (freespace) kirajzolásához a robot és
    minden pont közt — az OpenCV C++ alapja nagyságrendekkel gyorsabb,
    mint egy natív Python Bresenham-implementáció.
  - Szigorú Z-vágás (csak a szenzor magassága körüli szűk sáv) a
    "bólintó kutya" probléma ellen — járás közben a pitch/roll ingadozás
    miatt a padló/plafon simán "falnak" tűnhetne enélkül. Első körben
    NEM kompenzáljuk IMU roll/pitch-csel, csak szűken vágunk.
  - Extrinsic-figyelmeztetés: a Hesai szenzor pontos szerelési eltolása/
    forgása a robot testéhez képest MÉG NINCS megmérve (ld. showcase.html
    kommentje) — ez a script a szenzor lokális (x,y) koordinátáit
    közvetlenül a robot yaw-jával forgatja el, nulla extra eltolással.
    Első közelítésnek jó, finomítható majd valós kalibrációval.

Kimenet: PNG előnézet + egy JSON, aminek a formátuma megegyezik a
web_dashboard /slam_data végpontjának occupancy-grid alakjával
(width, height, resolution, origin_x, origin_y, data) — így később
közvetlenül betölthető a showcase.html már meglévő SLAM-panel
kirajzolójába, akár a rosbridge megkerülésével is.
"""

import argparse
import json

import cv2
import numpy as np

Z_BAND_HALF = 0.05  # méter — a "10 cm-es sáv" a szenzor magassága körül
MIN_RANGE_M = 0.5  # ennél közelebbi pontokat eldobjuk — a robot saját teste/lábai
MAX_RANGE_M = 5.0  # ennél távolabbi pontokat eldobjuk — szoba méretéhez igazítva, kiugró "tüskék" ellen
MAX_TILT_RAD = 0.30  # kb. 17 fok — ennél nagyobb pillanatnyi roll/pitch esetén eldobjuk a keretet
                      # (szélsőséges dőlésnél a kis szög közelítéssel dolgozó korrekció megbízhatatlan)


def load_frames(path):
    frames = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            frames.append(json.loads(line))
    return frames


def frame_to_world_points(frame):
    """Egy keret pontfelhőjét világ-koordinátákba forgatja/tolja el a robot
    saját pozíciója+yaw-ja alapján. Visszaad egy (N,2) numpy tömböt.

    FONTOS: a négylábú járás közben a robot teste erősen bólint/dől
    (pitch/roll) — nem csak forog a saját tengelye körül, ahogy egy kerekes
    robot tenné. Ha ezt nem kompenzáljuk, a szenzor-relatív Z-vágás egy
    ÁLLANDÓAN VÁLTOZÓ, döntött síkot vág ki a valós világból lépésenként,
    ami pont a bejárt útvonal mentén szór szét zajt (ezt láttuk is: a
    yaw-szinkronizálás után is megmaradt a folt). Ezért itt előbb 3D-ben
    "kiegyenesítjük" a pontfelhőt a roll/pitch alapján, MIELŐTT a Z-sávot
    és a 2D yaw-forgatást alkalmaznánk."""
    pts = frame.get("points") or []
    if not pts:
        return np.empty((0, 2))
    arr = np.asarray(pts, dtype=np.float32)  # (N, 4): x, y, z, intensity
    if arr.shape[0] == 0:
        return np.empty((0, 2))

    roll = frame.get("roll") or 0.0
    pitch = frame.get("pitch") or 0.0
    if abs(roll) > MAX_TILT_RAD or abs(pitch) > MAX_TILT_RAD:
        # Szélsőséges pillanatnyi dőlés (pl. lépés közbeni erős bicsaklás) —
        # inkább kihagyjuk ezt a keretet, mint hogy egy megbízhatatlan
        # korrekció távoli, kiugró "tüske" pontokat szórjon a térképre.
        return np.empty((0, 2))
    xyz = arr[:, :3].copy()
    if roll or pitch:
        cr, sr = np.cos(-roll), np.sin(-roll)
        cp, sp = np.cos(-pitch), np.sin(-pitch)
        # Rx(-roll) majd Ry(-pitch) — a testtel együtt dőlt pontfelhőt
        # visszaforgatja egy gravitáció-szinkronizált ("szintezett") keretbe.
        rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], dtype=np.float32)
        ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], dtype=np.float32)
        xyz = xyz @ rx.T @ ry.T

    # Szigorú Z-vágás — MOST már a szintezett (roll/pitch-kompenzált) Z-n.
    z_mask = np.abs(xyz[:, 2]) <= Z_BAND_HALF
    xyz = xyz[z_mask]
    if xyz.shape[0] == 0:
        return np.empty((0, 2))

    # Távolság-alapú zajszűrés — a MIN_RANGE_M kizárja a robot saját
    # testét/lábait (önárnyékolás).
    dist = np.hypot(xyz[:, 0], xyz[:, 1])
    range_mask = (dist >= MIN_RANGE_M) & (dist <= MAX_RANGE_M)
    xyz = xyz[range_mask]
    if xyz.shape[0] == 0:
        return np.empty((0, 2))

    x, y = frame.get("x") or 0.0, frame.get("y") or 0.0
    # Empirikus szenzor-extrinsic korrekció: egy forgó tesztsétán (walk_kicsi.jsonl,
    # ~95 fok yaw-tartomány) végigpásztázva a lehetséges eltolásokat, +90 fok adta
    # a legélesebb (legkevésbé "elkenődött") térképet — ez azt jelzi, hogy a Hesai
    # kb. 90 fokkal el van forgatva a feltételezett iránytól a robot testéhez képest.
    # Ld. a beszélgetésben a pásztázás eredményét (0 fok: 5299 akadály-cella,
    # 90 fok: 2397). Nincs pontosan megmért extrinsic, ez egy empirikus közelítés.
    YAW_OFFSET_RAD = np.radians(90)
    yaw = (frame.get("yaw") or 0.0) + YAW_OFFSET_RAD
    cos_y, sin_y = np.cos(yaw), np.sin(yaw)
    # 2D forgatásmátrix, vektorizáltan az összes ponton egyszerre.
    rot = np.array([[cos_y, -sin_y], [sin_y, cos_y]], dtype=np.float32)
    local_xy = xyz[:, :2]
    world_xy = local_xy @ rot.T
    world_xy[:, 0] += x
    world_xy[:, 1] += y
    return world_xy


def build_grid(frames, resolution):
    all_world_pts = []
    robot_positions = []
    for frame in frames:
        wpts = frame_to_world_points(frame)
        if wpts.shape[0]:
            all_world_pts.append(wpts)
        robot_positions.append((frame.get("x") or 0.0, frame.get("y") or 0.0))

    if not all_world_pts:
        raise RuntimeError("Nincs egyetlen érvényes pont sem a felvételben (Z-vágás/távolság-szűrés után).")

    pts = np.concatenate(all_world_pts, axis=0)
    robot_positions = np.asarray(robot_positions, dtype=np.float32)

    # Térkép-kiterjedés: minden pont + minden robot-pozíció + kis margó.
    all_xy = np.concatenate([pts, robot_positions], axis=0)
    min_x, min_y = all_xy.min(axis=0) - 1.0
    max_x, max_y = all_xy.max(axis=0) + 1.0

    width = int(np.ceil((max_x - min_x) / resolution))
    height = int(np.ceil((max_y - min_y) / resolution))
    width = max(width, 10)
    height = max(height, 10)

    # occupancy: -1 ismeretlen, 0 szabad, 100 akadály (ROS nav_msgs/OccupancyGrid konvenció)
    grid = np.full((height, width), -1, dtype=np.int16)

    def world_to_cell(wx, wy):
        cx = int((wx - min_x) / resolution)
        cy = int((wy - min_y) / resolution)
        return cx, cy

    # 1) szabad terület: cv2.line minden robot->pont sugárhoz — OpenCV C++
    #    alapon fut, nagyságrendekkel gyorsabb natív Python Bresenham-nél.
    free_mask = np.zeros((height, width), dtype=np.uint8)
    for frame, wpts in zip(frames, all_world_pts):
        if wpts.shape[0] == 0:
            continue
        rx, ry = frame.get("x") or 0.0, frame.get("y") or 0.0
        rcx, rcy = world_to_cell(rx, ry)
        # Ritkítás: minden N-edik sugarat rajzoljuk csak — de elég sűrűn
        # (max 1500/keret), különben a szabad terület alul-reprezentált
        # marad az akadály-jelöléshez képest, és a térkép feketébe fullad.
        step = max(1, wpts.shape[0] // 1500)
        for wx, wy in wpts[::step]:
            pcx, pcy = world_to_cell(wx, wy)
            cv2.line(free_mask, (rcx, rcy), (pcx, pcy), color=1, thickness=1)

    grid[free_mask == 1] = 0

    # 2) akadályok: NEM elég egyetlen pont — járás közben a robot pitch/roll
    #    bólintása miatt a szigorú Z-sáv is átenged néhány zaj-pontot minden
    #    keretben, ami egyetlen-hit logikával rögtön véglegesen "fallá"
    #    jelölne minden érintett cellát (ezt láttuk is: majdnem az egész
    #    térkép fekete lett). Ehelyett cellánként számoljuk, hány KÜLÖNBÖZŐ
    #    keretben találtuk el, és csak a küszöb felett soroljuk akadálynak.
    OCCUPIED_HIT_THRESHOLD = 3
    hit_counts = np.zeros((height, width), dtype=np.int32)
    cell_xy = np.floor((pts - np.array([min_x, min_y])) / resolution).astype(np.int32)
    valid = (cell_xy[:, 0] >= 0) & (cell_xy[:, 0] < width) & (cell_xy[:, 1] >= 0) & (cell_xy[:, 1] < height)
    cell_xy = cell_xy[valid]
    np.add.at(hit_counts, (cell_xy[:, 1], cell_xy[:, 0]), 1)
    grid[hit_counts >= OCCUPIED_HIT_THRESHOLD] = 100

    # (Megjegyzés: korábban itt volt egy morfológiai "nyitás" a zaj ellen,
    # de egy 3x3-as erózió egy VALÓDI, csak 1 cella vékony falat is teljesen
    # eltüntet 5cm/cella felbontásnál — ezt a tilt-kompenzáció bevezetése
    # után teszteltük egy mozdulatlan felvételen, és majdnem az összes fal
    # eltűnt tőle. Kivéve, amíg nincs jobb (pl. súlyozott/Bayes-i) megoldás.)

    return grid, min_x, min_y


def save_png(grid, path):
    img = np.zeros(grid.shape, dtype=np.uint8)
    img[grid == -1] = 120  # ismeretlen — szürke
    img[grid == 0] = 255  # szabad — fehér
    img[grid == 100] = 0  # akadály — fekete
    # A kép Y-tengelye lefelé nő, a világ-koordináta Y felfelé — a
    # megszokott térkép-nézethez (észak fent) függőlegesen tükrözzük.
    img = np.flipud(img)
    cv2.imwrite(path, img)


def save_json(grid, min_x, min_y, resolution, path):
    payload = {
        "width": int(grid.shape[1]),
        "height": int(grid.shape[0]),
        "resolution": resolution,
        "origin_x": float(min_x),
        "origin_y": float(min_y),
        "data": grid.astype(np.int16).flatten().tolist(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def main():
    ap = argparse.ArgumentParser(description="Saját occupancy grid építése egy data_logger.py felvételből.")
    ap.add_argument("input", help="a data_logger.py-vel mentett .jsonl fájl")
    ap.add_argument("--resolution", type=float, default=0.05, help="cella-méret méterben (alapértelmezett: 5cm)")
    ap.add_argument("--out-png", default=None, help="kimeneti PNG (alapértelmezett: <input>.png)")
    ap.add_argument("--out-json", default=None, help="kimeneti JSON (alapértelmezett: <input>.map.json)")
    ap.add_argument("--start", type=int, default=0, help="csak a start..start+limit keretek (szegmens-teszthez)")
    ap.add_argument("--limit", type=int, default=None, help="hány keretet vegyünk a start-tól")
    args = ap.parse_args()

    out_png = args.out_png or (args.input.rsplit(".", 1)[0] + ".png")
    out_json = args.out_json or (args.input.rsplit(".", 1)[0] + ".map.json")

    frames = load_frames(args.input)
    if args.limit is not None:
        frames = frames[args.start:args.start + args.limit]
    print(f"{len(frames)} keret betöltve: {args.input}")

    grid, min_x, min_y = build_grid(frames, args.resolution)
    n_free = int((grid == 0).sum())
    n_occ = int((grid == 100).sum())
    n_unknown = int((grid == -1).sum())
    print(f"Rács: {grid.shape[1]}x{grid.shape[0]} cella ({args.resolution}m/cella)")
    print(f"  szabad: {n_free}, akadály: {n_occ}, ismeretlen: {n_unknown}")

    save_png(grid, out_png)
    save_json(grid, min_x, min_y, args.resolution, out_json)
    print(f"Mentve: {out_png}, {out_json}")


if __name__ == "__main__":
    main()
