"""
mock_thermal — MLX90640 hőkamera (USB EVB board) adatforrás.

2026-09-04 este: a hardver fizikailag nincs csatlakoztatva, ezért ma este
KIZÁRÓLAG a szimulált (MOCK_MODE) ágat használjuk — nem telepítünk/
fordítunk semmilyen Linux USB drivert vagy natív Melexis-csomagot ma este.

A valós olvasás VÁZA elő van készítve (`read_real_frame`), de nincs
implementálva — az EVB board tipikusan virtuális COM porton (soros)
küldi a kereteket, ez a legvalószínűbb integrációs út holnapra, de a
pontos protokollt élő hardverrel kell megerősíteni, itt vaktában nem
implementáljuk.
"""

import math
import os

MOCK_MODE = os.environ.get("MOCK_SDK") == "1"

THERMAL_COLS, THERMAL_ROWS = 32, 24  # az MLX90640 natív felbontása


def mock_thermal_frame(t):
    """Szimulált hőtérkép — egy "meleg folt" (kb. testhőmérséklet) mozog
    hideg (~20°C) háttér előtt, hogy a frontend hőtérkép-kirajzolás
    tesztelhető legyen valós hardver nélkül. Sor-folytonos lista,
    THERMAL_COLS*THERMAL_ROWS elem, °C-ban."""
    cx = THERMAL_COLS / 2 + (THERMAL_COLS / 2 - 3) * math.sin(t * 0.3)
    cy = THERMAL_ROWS / 2
    grid = []
    for row in range(THERMAL_ROWS):
        for col in range(THERMAL_COLS):
            d = math.hypot(col - cx, row - cy)
            heat = 34.0 * math.exp(-(d ** 2) / (2 * 4.0 ** 2))  # ~testhő a folt közepén
            noise = 0.3 * math.sin(t * 5 + col * 0.7 + row * 1.3)
            grid.append(round(20.0 + heat + noise, 2))
    return grid


def read_real_frame(serial_port="/dev/ttyACM0", baudrate=115200):
    """VÁZ, NINCS IMPLEMENTÁLVA — a valós MLX90640 EVB board tipikusan
    virtuális COM/soros porton küldi a kereteket. Élő hardverrel kell
    megerősíteni a pontos keret-protokollt (fejléc, checksum, bájt-sorrend),
    mielőtt ez elkészül. Addig hívása NotImplementedError-t dob, hogy
    véletlenül se próbáljon MOCK_MODE=False mellett hallgatólagosan
    hibás/üres adatot visszaadni."""
    raise NotImplementedError(
        "read_real_frame: az EVB board soros protokollja még nincs megerősítve élő hardverrel"
    )


def get_thermal_frame(t):
    """Visszaad egy hőkeretet, vagy None-t, ha nincs elérhető adatforrás
    (pl. éles SDK-módban, de a hardver fizikailag nincs csatlakoztatva —
    ld. 2026-09-05 esti helyzet). A hívónak (app.py /api/thermal_stream)
    ezt kezelnie kell, nem szabad emiatt elszállnia a végpontnak."""
    if MOCK_MODE:
        return mock_thermal_frame(t)
    try:
        return read_real_frame()
    except NotImplementedError:
        return None
