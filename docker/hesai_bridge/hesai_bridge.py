"""
UDP bridge a Hesai PandarXT-16 (a NERO_GO2 robotra 2026-09-04-én felszerelt
külső navigációs LiDAR) nyers point-cloud csomagjaihoz.

A csomagformátum SEHOL nincs a hivatalos Hesai kézikönyvben dokumentálva
("contact Hesai technical support") — ez a dekóder a hivatalos, nyílt
forráskódú ROS-driverből (HesaiTechnology/HesaiLidar_General_ROS,
src/.../pandarXT.h + pandarGeneral_internal.cc, ParseXTData +
CalcXTPointXYZIT függvények) van visszafejtve, 1:1 megfeleltetve.

Csomagformátum (568 bájt, PandarXT-16, `chLaserNumber=16`, `chBlockNumber=8`):
  Fejléc (12 bájt):
    [0:2]  sob        big-endian, MINDIG 0xEEFF
    [6]    chLaserNumber   (16)
    [7]    chBlockNumber   (8)
    [9]    chDisUnit       (4 = mm/egység)
  Törzs (8 blokk × (2 + 16×4) = 528 bájt):
    blokkonként:
      [0:2]  azimuth        little-endian, RealAzimuth*100 (centifok)
      16×egység, egységenként 4 bájt:
        [0:2]  distance-raw   little-endian; méter = raw*chDisUnit/1000
        [2]    intensity
        [3]    confidence
  Farok (28 bájt, csak részben használjuk): echo, spin_speed stb.

XYZ-átszámítás (CalcXTPointXYZIT, korrekció NÉLKÜLI ág — ez a robot
demóhoz elég pontos, a finomkorrekciós tag a hivatalos driverben csak
azimut-fok-tört pontosságú javítás):
  elevation_deg[i] = pandarXT_elev_angle_map[i*2]  (XT16: 16 csatorna,
    +15°..-15°, 2°-onként — a driver a 32-csatornás XT32 táblázat minden
    MÁSODIK értékét használja XT16-nál)
  xyDistance = distance * cos(elevation)
  x = xyDistance * sin(azimuth)
  y = xyDistance * cos(azimuth)
  z = distance * sin(elevation)
"""

import json
import logging
import math
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Csak a Python standard könyvtárára épül (nincs Flask/pip-függőség) —
# a robot internete ma este ismételten megbízhatatlanná vált, ez a
# szolgáltatás így internet nélkül is buildelhető/futtatható.

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nero_go2.hesai_bridge")

UDP_PORT = 2368
HEADER_SIZE = 12
BLOCK_HEADER_SIZE = 2
UNIT_SIZE = 4
TAIL_SIZE = 28
EXPECTED_LASER_NUM = 16
EXPECTED_BLOCK_NUM = 8

# XT32 elevációs tábla — XT16 minden MÁSODIK értékét használja (a hivatalos
# driver forrása szerint: pandarXT_elev_angle_map[i*2]).
_XT32_ELEV_MAP = [
    15.0, 14.0, 13.0, 12.0, 11.0, 10.0, 9.0, 8.0,
    7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0,
    -1.0, -2.0, -3.0, -4.0, -5.0, -6.0, -7.0, -8.0,
    -9.0, -10.0, -11.0, -12.0, -13.0, -14.0, -15.0, -16.0,
]
XT16_ELEV_RAD = [math.radians(_XT32_ELEV_MAP[i * 2]) for i in range(16)]
XT16_ELEV_SIN = [math.sin(a) for a in XT16_ELEV_RAD]
XT16_ELEV_COS = [math.cos(a) for a in XT16_ELEV_RAD]

_state_lock = threading.Lock()
_state = {
    "connected": False,
    "latest_points": None,  # list of [x, y, z, intensity]
    "packet_count": 0,
    "last_packet_time": None,
    "spin_speed": None,
}


def _set_state(**kwargs):
    with _state_lock:
        _state.update(kwargs)


def _get_state():
    with _state_lock:
        return dict(_state)


def _parse_packet(buf):
    """Egyetlen 568 bájtos PandarXT-16 UDP csomagot dekódol pontlistává.
    Visszaad None-t, ha a csomag nem PandarXT-16 formátumú."""
    if len(buf) < HEADER_SIZE + 2:
        return None

    sob = (buf[0] << 8) | buf[1]
    if sob != 0xEEFF:
        return None

    laser_num = buf[6]
    block_num = buf[7]
    dis_unit = buf[9]  # mm/egység, jellemzően 4

    if laser_num != EXPECTED_LASER_NUM or block_num != EXPECTED_BLOCK_NUM:
        # Más Pandar-modell (pl. XT32/XTM) csomagja lehet - most csak
        # a robotra ténylegesen felszerelt XT16-ot dolgozzuk fel.
        return None

    points = []
    idx = HEADER_SIZE
    for _block in range(block_num):
        if idx + BLOCK_HEADER_SIZE > len(buf):
            break
        azimuth_raw = buf[idx] | (buf[idx + 1] << 8)  # little-endian, RealAzimuth*100
        idx += BLOCK_HEADER_SIZE
        azimuth_rad = math.radians(azimuth_raw / 100.0)
        sin_az, cos_az = math.sin(azimuth_rad), math.cos(azimuth_rad)

        for unit_i in range(laser_num):
            if idx + UNIT_SIZE > len(buf):
                break
            dist_raw = buf[idx] | (buf[idx + 1] << 8)
            intensity = buf[idx + 2]
            idx += UNIT_SIZE

            distance_m = dist_raw * dis_unit / 1000.0
            if distance_m <= 0.1 or distance_m > 200.0:
                continue

            sin_el, cos_el = XT16_ELEV_SIN[unit_i], XT16_ELEV_COS[unit_i]
            xy_dist = distance_m * cos_el
            x = xy_dist * sin_az
            y = xy_dist * cos_az
            z = distance_m * sin_el
            points.append([round(x, 3), round(y, 3), round(z, 3), intensity])

    return points


def _udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    logger.info("UDP listener started on port %d", UDP_PORT)

    # Több csomagot gyűjtünk össze egy "frame"-be (egy teljes 360°-os
    # körbeforgás sok csomagból áll), mielőtt publikáljuk - így a /lidar
    # végpont egy összefüggő, teljes pontfelhőt ad, nem csak 8 blokknyit.
    frame_buffer = []
    last_publish = time.time()
    FRAME_INTERVAL_S = 0.2  # ~5 Hz frissítés, elég egy élő demóhoz

    while True:
        try:
            data, _addr = sock.recvfrom(2048)
        except Exception:
            logger.exception("UDP recv error")
            continue

        points = _parse_packet(data)
        if points is None:
            continue

        frame_buffer.extend(points)
        _set_state(connected=True, packet_count=_state["packet_count"] + 1, last_packet_time=time.time())

        now = time.time()
        if now - last_publish >= FRAME_INTERVAL_S:
            # Ritkítás, hogy a HTTP-válasz ne nőjön parttalanul nagyra.
            pts = frame_buffer
            if len(pts) > 8000:
                step = len(pts) // 8000
                pts = pts[::step][:8000]
            _set_state(latest_points=pts)
            frame_buffer = []
            last_publish = now


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
        if self.path == "/health":
            self._send_json({"status": "ok", "connected": s["connected"], "packet_count": s["packet_count"]})
        elif self.path == "/lidar":
            if s["latest_points"] is None:
                self._send_json({"error": "no lidar data yet"}, status=404)
            else:
                self._send_json(s["latest_points"])
        else:
            self._send_json({"error": "not found"}, status=404)

    def log_message(self, fmt, *args):
        pass  # a Flask-alapú testvér-szolgáltatásokkal egyező, csendes log


def main():
    listener = threading.Thread(target=_udp_listener, daemon=True)
    listener.start()
    server = ThreadingHTTPServer(("0.0.0.0", 5003), _Handler)
    logger.info("HTTP API listening on :5003")
    server.serve_forever()


if __name__ == "__main__":
    main()
