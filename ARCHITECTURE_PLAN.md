# 🏗️ NERO GO2 — Architekturális Refaktorálási & Moduláris Terv

> **Cél:** A kód szétbombázása nélkül, fokozatosan átállni egy tisztább, AI-barát, könnyen tesztelhető és moduláris architektúrára.

---

## 1. Jelenlegi Architekturális Szűk Keresztmetszetek
1. **Monolitikus Script-ek:** A `benchmark_3d.py` és a korábbi html generálók túl sok felelősséget (adatbetöltés, ICP számítás, HTML template összefűzés) egyetlen fájlban kezeltek.
2. **Keményen Kódolt Konfigurációk:** A szenzor kalibrációs értékek (`0.99x` gyro skála, `96.0°` yaw offset, IP-címek) több scriptben szétszórva szerepelnek.
3. **Élő Robot Függőség a Tesztelésnél:** Nehéz volt tesztelni a felületet fizikai robot nélkül.

---

## 2. Javasolt Moduláris Szerkezet (Refaktorálási Lépések)

### A. Konfiguráció Központosítása (`config/`)
Hozzunk létre egy központi YAML/JSON konfigurációs fájlt, ahonnan minden modul felolvassa a beállításokat:
```
c:\Users\user\NERO_GO2\config\
├── sensors.yaml         # Hesai offsetek, Gyro skála, szögkorrekciók
├── network.yaml         # IP-címek, portok, Docker kapcsolódások
└── slam_params.yaml     # KISS-ICP voxel méret, max_range, min_range
```

### B. Robot API Interfész Leválasztása (`core/robot_interface/`)
Egy absztrakt Python interfész (`RobotBridge`) bevezetése, amely mögött két megvalósítás futhat:
1. `LiveRobotBridge` (Valós CycloneDDS + UDP stream)
2. `MockRobotBridge` (Pre-recorded `.jsonl` adatsorok visszajátszása)
*Előny:* Az AI és a frontend tesztelhető fizikai robot jelenléte nélkül is.

### C. Ágens-Konfigurációk & Promptok Mappája (`agents/`)
Az AI ágensek speciális feladatainak (pl. SLAM paraméter-hangoló, diagnosztikai ellenőr) promptjait és szabályait különítsük el:
```
c:\Users\user\NERO_GO2\agents\
├── slam_tuner_prompt.md
├── hardware_diagnostics_prompt.md
└── safety_guard_rules.md
```

### D. Tiszta Végpont-Separálás a Backendben (`docker/web_dashboard/`)
- `routes/telemetry.py` — SSE adatszórás
- `routes/slam.py` — 3D pontfelhők és 2D térképek
- `routes/control.py` — Mozgásvezérlő parancsok

---

## 3. Ütemezési Terv a Refaktorálásra
1. **1. Lépés:** Konfigurációs fájlok kiszervezése (`config/`).
2. **2. Lépés:** `MockRobotBridge` és `LiveRobotBridge` interfész elkészítése.
3. **3. Lépés:** Végpontok moduláris bontása.
*Minden lépés végén automatikus visszafele-kompatibilitási tesztet futtatunk.*
