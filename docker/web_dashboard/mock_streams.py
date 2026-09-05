"""
mock_streams — szimulált odometria a MOCK_SDK=1 fejlesztéshez, amikor a
robot fizikailag nincs jelen (2026-09-04 este, holnapi bemutató előkészítése).

Csak egy egyszerű körpályát ad vissza (x, y, yaw) az idő függvényében —
ennyi elég ahhoz, hogy a frontend waypoint-kattintás + navigáció-UI
végigtesztelhető legyen anélkül, hogy a valós SDK-hoz vagy a robothoz
kellene nyúlni. Holnap reggel, éles SDK-módban ez a modul egyszerűen nem
kerül felhasználásra (app.py _init_sdk() a valós SportModeState_-ből tölti
a pozíciót) — nem kell semmit kicserélni, csak MOCK_SDK=0-val indítani.
"""

import math

CIRCLE_RADIUS_M = 1.5
CIRCLE_PERIOD_S = 40.0  # ennyi idő alatt fut körbe egyet


def mock_detection(t):
    """Szimulált "person" detekció a Security Robot Mód demózásához — nincs
    valós OpenCV/YOLO ma este, csak egy periodikusan felbukkanó/eltűnő
    bounding box, hogy a frontend cél kereszt + UI végigtesztelhető legyen.
    Holnap reggel ez a függvény cserélendő a valós detektor kimenetére
    (ugyanaz a {detected, bbox, confidence} alak várt)."""
    cycle = t % 12.0
    detected = cycle < 7.0  # 7s látható, 5s nincs detekció
    if not detected:
        return {"detected": False, "bbox": None, "confidence": 0.0}
    # bbox: [x0, y0, x1, y1] relatív (0..1) koordináták a kamera-képhez képest,
    # lassan mozog a keretben — imitálja, hogy a "célpont" sétál.
    cx = 0.5 + 0.25 * math.sin(cycle * 0.8)
    cy = 0.5
    hw, hh = 0.12, 0.28
    confidence = 0.80 + 0.15 * abs(math.sin(cycle * 2.0))
    return {
        "detected": True,
        "bbox": [round(cx - hw, 3), round(cy - hh, 3), round(cx + hw, 3), round(cy + hh, 3)],
        "confidence": round(confidence, 3),
    }


def mock_position(t):
    """Visszaadja a szimulált (x, y, yaw) pozíciót t másodpercnél, egy
    origó körüli körpályán haladva (óramutató járásával megegyezően)."""
    angle = 2 * math.pi * (t % CIRCLE_PERIOD_S) / CIRCLE_PERIOD_S
    x = CIRCLE_RADIUS_M * math.cos(angle)
    y = CIRCLE_RADIUS_M * math.sin(angle)
    # A pálya érintőjének iránya (a haladási irány) — ez a "yaw", nem a
    # sugárirány, mert a robot előre néz, amerre halad.
    yaw = angle + math.pi / 2
    return round(x, 3), round(y, 3), round(((yaw + math.pi) % (2 * math.pi)) - math.pi, 3)
