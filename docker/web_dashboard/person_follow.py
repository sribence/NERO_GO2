""""Kövesd a mozgó embert" mód — tiszta, SDK-fuggetlen szabalyozo-logika.

A minta ugyanaz, mint compute_nav_command / compute_tracking_command app.py-ban
(ld. "Navigacio" es "Security mod" szekciok): a matematikat kulon, Flask/SDK/
YOLO-fuggetlen fuggvenyekbe tesszuk, hogy egyszeruen tesztelheto legyen, es
csak a hivo oldal (app.py _follow_thread) kototte be a valos
sport_client.Move()-ba — az MAR a meglevo watchdog/E-stop/armed-gate alatt fut,
ez a modul semmilyen uj hardver-fele parancsutat nem nyit.

YOLO-detekcio bemenete: yolo_detector.detect() kimenete
(ld. ../realsense_bridge/yolo_detector.py) — {"detections": [{"class",
"class_id", "confidence", "bbox": {"x1","y1","x2","y2"}}, ...]}.
"""
from __future__ import annotations

import math

# --- Sebesseg-korlatok — kovesd-az-embert mod, konzervativ (ld. feladat:
# ez a robotot TENYLEGESEN egy ember fele mozgatja, felugyelet nelkul, amig
# aktiv — ovatosabb, mint a joystick MOVE_SPEED=0.5-e, es a NAV_MAX_VX=0.25-nel
# is alacsonyabb, mert itt a "cel" (ember) maga is mozoghat kiszamithatatlanul).
FOLLOW_MAX_VX = 0.4  # m/s
FOLLOW_MAX_VYAW = 0.8  # rad/s

# P-szabalyozo egyutthatok
FOLLOW_KP_ANG = 1.5  # vizszintes offset (-0.5..0.5) -> vyaw
FOLLOW_KP_LIN = 1.2  # meret-hiba -> vx

# Cel: a szemely bbox-magassaga a kepmagassag ekkora reszet toltse ki —
# ez a "tavolsag" proxy-ja YOLO-nal (nincs valos melyseg-mereses ebben a
# modban, csak a 2D bbox meretebol becsulunk). Ha a bbox ennel nagyobb,
# a szemely tul kozel van -> nem megy tovabb elore (nem all hatra sem,
# ld. clamp alul-korlatja 0.0-n).
FOLLOW_TARGET_SIZE_FRAC = 0.35
# Ezen a hataron belul a meret-hiba "zajnak" szamit, nem indit el mozgast —
# kulonben egy stabilan allo celnal is remeg a sebesseg a bbox pixel-szintu
# ingadozasa miatt.
FOLLOW_SIZE_DEADBAND = 0.03
# Ugyanez vizszintesen — a kep kozepe korul ne remegjen a forgas.
FOLLOW_CENTER_DEADBAND = 0.03

# Minimum konfidencia, hogy egy "person" detekciot egyaltalan figyelembe
# vegyunk celkent (a YOLOv8n gyakran ad alacsony-konfidencias zaj-detekciot).
FOLLOW_MIN_CONFIDENCE = 0.45

# Ha ennyi ideig (mp) nincs "person" detekcio, a robotot le kell allitani —
# ne menjen tovabb "vakon" a legutobb ismert iranyba.
FOLLOW_PERSON_LOST_TIMEOUT_S = 2.0


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def pick_person_target(detections, min_confidence=FOLLOW_MIN_CONFIDENCE):
    """detections: yolo_detector.detect()["detections"] lista.
    Kivalasztja a legnagyobb bbox-teruletu "person" detekciot a
    min_confidence felettiek kozul (a nagyobb bbox altalaban a
    kozelebbi/dominansabb celt jelenti a kepen — ez a "largest" kritérium
    a feladatból; a confidence-szűrés a "most-confident" felét fedi le:
    zajos, alacsony-konfidenciás észlelések már nem versenyeznek).
    Nincs megfelelo jelolt eseten None-t ad vissza."""
    best = None
    best_area = -1.0
    for det in detections or []:
        if det.get("class") != "person":
            continue
        if det.get("confidence", 0.0) < min_confidence:
            continue
        bbox = det.get("bbox") or {}
        try:
            w = bbox["x2"] - bbox["x1"]
            h = bbox["y2"] - bbox["y1"]
        except KeyError:
            continue
        area = w * h
        if area > best_area:
            best_area = area
            best = det
    return best


def compute_follow_command(bbox, frame_width, frame_height):
    """TISZTA fuggveny — bbox (dict x1,y1,x2,y2, pixel-koordinatak) +
    a kepkocka merete alapjan visszaad egy (vx, vyaw) part, mar
    korlatozva FOLLOW_MAX_VX / FOLLOW_MAX_VYAW-ra.

    Nem hivja az SDK-t, nem olvas/ir globalis allapotot — ld. a modul-
    docstringben leirt minta (compute_nav_command app.py-ban)."""
    if frame_width <= 0 or frame_height <= 0:
        return 0.0, 0.0

    cx = (bbox["x1"] + bbox["x2"]) / 2.0
    bbox_h = bbox["y2"] - bbox["y1"]

    # Vizszintes iranyu forgas: a bbox-kozep kepkozeptol valo eltolasa,
    # -0.5..+0.5 skalan (0 = pontosan kozepen).
    offset = (cx / frame_width) - 0.5
    if abs(offset) < FOLLOW_CENTER_DEADBAND:
        vyaw = 0.0
    else:
        vyaw = _clamp(-FOLLOW_KP_ANG * offset, -FOLLOW_MAX_VYAW, FOLLOW_MAX_VYAW)

    # Elore-hatra: a bbox-magassag a kepmagassaghoz viszonyitva a
    # "tavolsag" proxy-ja — kisebb bbox = tavolabbi szemely = menjen elore.
    # Csak ELORE megy soha hatra (a feladat konzervativ kovetest ker, nem
    # aktiv visszahuzodast egy tul-kozeli szemelytol).
    size_frac = bbox_h / frame_height
    size_error = FOLLOW_TARGET_SIZE_FRAC - size_frac
    if abs(size_error) < FOLLOW_SIZE_DEADBAND:
        vx = 0.0
    else:
        vx = _clamp(FOLLOW_KP_LIN * size_error, 0.0, FOLLOW_MAX_VX)

    return vx, vyaw


def person_lost(last_seen_ts, now_ts, timeout_s=FOLLOW_PERSON_LOST_TIMEOUT_S):
    """TISZTA fuggveny: True, ha last_seen_ts ota tobb, mint timeout_s
    mp telt el (vagy last_seen_ts meg None, azaz sosem lattunk semelyt).
    now_ts explicit parameter, nem time.time() belul — igy a tesztek
    valodi ido-varakozas nelkul, determinisztikusan futnak."""
    if last_seen_ts is None:
        return True
    return (now_ts - last_seen_ts) > timeout_s
