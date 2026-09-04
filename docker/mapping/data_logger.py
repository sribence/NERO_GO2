"""
NERO_GO2 térkép-adat-dömper — "ne a roboton fejlesszen" workflow 1. lépése.

Ahelyett, hogy a térképépítő algoritmust élesben, a bekapcsolt robotnál
debugolnánk (lemerülő akku, megszakadó wifi, mozgó célpont), ez a script
egy rövid sétát rögzít fájlba: időbélyeg + a robot saját (SDK-ból jövő)
pozíció/yaw-becslése + a Hesai LiDAR nyers pontfelhője, 5-10 Hz-en.

FONTOS: ez a script a FEJLESZTŐI GÉPEDEN fut (nem a roboton/Jetsonon) —
csak HTTP GET-tel kérdezi le a már futó web_dashboard (:5002) és
hesai_bridge (:5003) szolgáltatásokat, semmit nem telepít/futtat a
robotnál, ld. docs/00-BIZTONSAGI-SZABALYOK.md.

Formátum: .jsonl (soronként egy JSON-objektum), nem .npz — mert a
pontfelhő mérete keretenként változó, és így a felvétel akkor is
megmenthető, ha a script menet közben megszakad (minden sor azonnal
lemezre íródik, nincs egyetlen nagy archívum-írás a végén).

Használat:
    python data_logger.py --duration 90 --hz 8 --out walk_2026-09-04.jsonl
"""

import argparse
import json
import time

import requests

DEFAULT_DASHBOARD_URL = "http://192.168.123.18:5002"
DEFAULT_HESAI_BRIDGE_URL = "http://192.168.123.18:5003"


def fetch_frame(dashboard_url, hesai_url, timeout=1.0):
    pose = requests.get(f"{dashboard_url}/pose_snapshot", timeout=timeout).json()
    lidar_resp = requests.get(f"{hesai_url}/lidar", timeout=timeout)
    points = lidar_resp.json() if lidar_resp.status_code == 200 else []
    return {
        "t": time.time(),
        "x": pose.get("position_x"),
        "y": pose.get("position_y"),
        "yaw": pose.get("yaw"),
        "roll": pose.get("roll"),
        "pitch": pose.get("pitch"),
        "points": points,  # [[x, y, z, intensity], ...] a hesai_bridge saját koordinátarendszerében
    }


def main():
    ap = argparse.ArgumentParser(description="NERO_GO2 séta-felvétel a saját térkép-építőhöz.")
    ap.add_argument("--duration", type=float, default=90, help="felvétel hossza másodpercben")
    ap.add_argument("--hz", type=float, default=8, help="mintavételi frekvencia")
    ap.add_argument("--out", default=f"walk_{int(time.time())}.jsonl", help="kimeneti .jsonl fájl")
    ap.add_argument("--dashboard-url", default=DEFAULT_DASHBOARD_URL)
    ap.add_argument("--hesai-url", default=DEFAULT_HESAI_BRIDGE_URL)
    args = ap.parse_args()

    period = 1.0 / args.hz
    n_frames = 0
    n_errors = 0
    start = time.time()

    print(f"Felvétel indul: {args.duration}s, {args.hz} Hz, cél: {args.out}")
    print("Séta közben ezt a scriptet futni kell hagyni — Ctrl+C-vel bármikor leállítható, a mentett rész megmarad.")

    with open(args.out, "a", encoding="utf-8") as f:
        try:
            while time.time() - start < args.duration:
                tick = time.time()
                try:
                    frame = fetch_frame(args.dashboard_url, args.hesai_url)
                    f.write(json.dumps(frame) + "\n")
                    f.flush()
                    n_frames += 1
                    if n_frames % max(1, int(args.hz)) == 0:
                        elapsed = time.time() - start
                        print(f"  {elapsed:5.1f}s | frame {n_frames:4d} | pos=({frame['x']}, {frame['y']}) yaw={frame['yaw']} | pontok={len(frame['points'])}")
                except requests.RequestException as e:
                    n_errors += 1
                    print(f"  hiba (kihagyva): {e}")
                sleep_left = period - (time.time() - tick)
                if sleep_left > 0:
                    time.sleep(sleep_left)
        except KeyboardInterrupt:
            print("\nMegszakítva — a mentett rész megvan.")

    print(f"\nKész: {n_frames} keret mentve ({n_errors} hiba) -> {args.out}")


if __name__ == "__main__":
    main()
