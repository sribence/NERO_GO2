"""
NERO GO2 — Mock Hesai bridge. Szimulalja a valodi hesai_bridge.py HTTP API-jat
(/health, /lidar) offline teszteshez, robot nelkul. Adatforras: korabbi
jsonl felvetel (walk_kicsi.jsonl) frame-enkent korbejarva, vagy szintetikus
kor alaku pontfelho ha nincs jsonl.
"""

import json
import math
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_JSONL = os.path.join(os.path.dirname(__file__), "..", "mapping", "walk_kicsi.jsonl")
PORT = 5003
FRAME_INTERVAL_S = 0.2  # ugyanaz az ~5 Hz mint az eles bridge

_state_lock = threading.Lock()
_state = {"connected": True, "packet_count": 0, "latest_points": None}


def _set_state(**kwargs):
    with _state_lock:
        _state.update(kwargs)


def _get_state():
    with _state_lock:
        return dict(_state)


def _load_frames_from_jsonl(path):
    frames = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            pts = data.get("points", [])
            if pts:
                frames.append(pts)
    return frames


def _synthetic_frame(step):
    """Kor alaku dummy pontfelho, ha nincs jsonl adat."""
    pts = []
    radius = 3.0 + 0.3 * math.sin(step / 20.0)
    for i in range(360):
        angle = math.radians(i)
        x = round(radius * math.cos(angle), 3)
        y = round(radius * math.sin(angle), 3)
        z = round(random.uniform(-0.2, 0.2), 3)
        pts.append([x, y, z, 50])
    return pts


def _frame_publisher():
    frames = []
    if os.path.exists(DEFAULT_JSONL):
        try:
            frames = _load_frames_from_jsonl(DEFAULT_JSONL)
            print(f"[MOCK-BRIDGE] {len(frames)} frame betoltve: {DEFAULT_JSONL}")
        except Exception as e:
            print(f"[MOCK-BRIDGE] jsonl betoltes hiba ({e}), szintetikus mod")

    idx = 0
    packet_count = 0
    while True:
        if frames:
            pts = frames[idx % len(frames)]
        else:
            pts = _synthetic_frame(idx)
        idx += 1
        packet_count += 1
        _set_state(connected=True, packet_count=packet_count, latest_points=pts)
        time.sleep(FRAME_INTERVAL_S)


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        s = _get_state()
        req_path = self.path.split("?")[0]

        if req_path == "/health":
            self._send_json({"status": "ok", "connected": s["connected"], "packet_count": s["packet_count"]})
        elif req_path == "/lidar":
            if s["latest_points"] is None:
                self._send_json({"error": "no lidar data yet"}, status=404)
            else:
                self._send_json(s["latest_points"])
        else:
            self._send_json({"error": "not found"}, status=404)

    def log_message(self, fmt, *args):
        pass


def main():
    publisher = threading.Thread(target=_frame_publisher, daemon=True)
    publisher.start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), _Handler)
    print(f"[MOCK-BRIDGE] HTTP API listening on :{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
