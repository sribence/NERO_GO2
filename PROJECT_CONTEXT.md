> **[Klón: C:SERSSERNERO_GO2 � SLAM/DOCS áG]**
# 🤖 NERO GO2 — AI Project Context & Operational Rules

## 1. Project Overview
A **NERO GO2** projekt célja a Unitree Go2 Edu négylábú robot és a rá szerelt szenzorok (Hesai PandarXT-16 3D LiDAR, Intel RealSense D435i, robot IMU) adatainak integrálásával egy valós idejű, robot-odometriától független, szoba- és épületszintű 3D SLAM térképező és autonóm navigációs rendszer kiépítése.

### Komponensek és Ágensek kapcsolódása:
- **Alacsony szintű mozgásvezérlés (MCU):** `192.168.123.161` — CycloneDDS kommunikáció a robot láb/motor rendszere felé.
- **Fedélzeti számítási egység (Jetson Orin Dokk):** `192.168.123.18` — Ubuntu Linux, Docker konténerekben futó szolgáltatások.
- **LiDAR Szenzor:** Hesai PandarXT-16 (`192.168.123.20`), UDP pontfelhő adatfolyam (360° FOV, 16 csatorna).
- **Web Dashboard & digitális iker:** Flask backend + SSE + Vanilla JS / Three.js 60 FPS WebGL felület (`:5002`, `:8080`, `:8088`).
- **AI Ágensek szerepe:** Autonóm állapotfelmérés, feladattervezés, pontfelhő-feldolgozási paraméterek dinamikus hangolása és felületkezelés.
> **[Klón: C:devNERO_GO2 — mission-control ág]**
# 🤖 NERO GO2 (dev/mission-control) — AI Project Context & Operational Rules

## 0. Ez a klón vs. a testvér-klón (KRITIKUS, elsőként olvasd)

Két külön lokális klón létezik ugyanabból a `github.com/sribence/NERO_GO2` repóból,
mindkettő a közös `908a031` pontról ágazott el, **egyik sincs push-olva** upstreamre:

| | Ez a klón | Testvér-klón |
|---|---|---|
| Útvonal | `C:\dev\NERO_GO2` | `C:\Users\user\NERO_GO2` |
| Ág fókusza | `mission-control/` operátori rendszer | SLAM/pontfelhő-feldolgozás (KISS-ICP, pose graph) |
| Egyedi tartalom | `mission-control/`, `xavier-pickerbot/` | `docs/17-19`, önálló SLAM-motorok |
| origin/main-től | 5 commit előrébb | 4 commit előrébb |

**Ne keverd a kettőt.** Ha SLAM/pontfelhő-munka kell, az a testvér-klónban van.
Ha `mission-control` (9 pillér, operátori HUD, multi-robot) a téma, itt vagy jó helyen.
A két ág egyesítése (merge) még nyitott feladat — ld. [TODO.md](TODO.md).

---

## 1. Project Overview

A **NERO GO2 mission-control** egy enterprise-igényű operátori irányító rendszer a
Unitree Go2 EDU négylábú robothoz: autonóm padló+fal térképezés, kattints-a-térképre
navigáció, multi-protokoll task-orchestration (WebSocket/MQTT/REST), on-demand
szenzor-parancsok, multi-kamera, esemény-vezérelt hang, feketedoboz-naplózás,
Tailscale távoli elérés, 3D digitális iker operátori felület.

Testvér-projekt: **Xavier Pickerbot Mini** ([xavier-pickerbot/](xavier-pickerbot/)) —
mecanum-alvázas karos robot, saját irányítópulttal és oktatási platform tervvel,
jelenleg **külön** rendszer (más hálózat, más stack) — összekötése a `mission-control`-lal
tervezett, de nincs megvalósítva (ld. TODO).

### Komponensek és ágensek kapcsolódása

- **Alacsony szintű mozgásvezérlés (MCU):** `192.168.123.161` — CycloneDDS a robot láb/motor rendszere felé.
- **Fedélzeti számítási egység (Jetson Orin Dokk):** `192.168.123.18` — Ubuntu 20.04.5 LTS, Docker konténerek.
- **Hesai PandarXT-16 külső LiDAR:** `192.168.123.20`, UDP pontfelhő.
- **RealSense D435i:** beépített (EDU-specifikus) mélységkamera — USB hardver-hiba miatt jelenleg parkoltatva.
- **mission-control:** 9 önálló pillér, mindegyik saját HTTP-porton, közös `core` robot-állapot proxy mögött.

---

## 2. Current Stack & Architecture

> **[Klón: C:SERSSERNERO_GO2 � SLAM/DOCS áG]**
### Technológiai Stakk:
- **Backend:** Python 3.10+, Flask, SSE (Server-Sent Events), Open3D, KISS-ICP (PRBonn Pure LiDAR Odometry).
- **Frontend:** Vanilla JavaScript (ES6+), HTML5, Three.js WebGL (stílus: sötét, cyber-industrial UI). **Nincs React/Vue!**
- **Infrastruktúra:** Docker, Docker Compose, CycloneDDS, ROS2 Foxy (konténerekben izolálva).
- **Operációs rendszerek:** Windows 11 (fejlesztői gép), Ubuntu 20.04 LTS (Jetson Orin).

### Mappastruktúra:
```
c:\Users\user\NERO_GO2\
├── CLAUDE.md                    # Szigorú fejlesztési szabályok
├── PROJECT_SUMMARY.md           # Benchmark és SLAM eredmények
├── PROJECT_CONTEXT.md           # Ez a fájl (AI kontextus)
├── TODO.md                      # Feladatlista és roadmap
├── ARCHITECTURE_PLAN.md         # Refaktorálási és moduláris terv
├── docker/
│   ├── hesai_bridge/            # Hesai LiDAR UDP/TCP bridge
│   ├── web_dashboard/           # Flask webes irányítópult és digitális iker
│   └── mapping/                 # SLAM feldolgozó motorok (run_kiss_icp.py, stb.)
├── docs/                        # Részletes műszaki dokumentációk (00-18)
└── scratch/                     # Segéd- és automatizálási skriptek
```

> **[Klón: C:devNERO_GO2 — mission-control ág]**
### Tech stack
- **Backend:** Python 3.11, FastAPI + uvicorn minden pilléren, `paho-mqtt`, `redis` (pub/sub event bus), `unitree_sdk2py` (natív DDS SportClient).
- **Frontend:** vanilla JS + three.js (CDN, build nélkül) — `digital-twin` 3D nézet. Fő repó `web_dashboard`: Flask + Jinja + vanilla JS. **Nincs React/Vue.**
- **Infrastruktúra:** Docker Compose (9 mikroszolgáltatás + Redis + Mosquitto), Tailscale (userspace networking, Docker-only).
- **Robot-kommunikáció:** ROS2/`rosbridge_suite` **tudatosan kihagyva** (SIGSEGV `network_mode: host`-on, megoldatlan) — helyette (1) hivatalos WebRTC (`webrtc_bridge`), (2) natív `unitree_sdk2py` DDS SportClient, `rclpy`/`rmw` réteg nélkül.

### Mappastruktúra

```
C:\dev\NERO_GO2\
├── CLAUDE.md                    # Szigorú fejlesztési szabályok
├── PROJECT_CONTEXT.md           # Ez a fájl
├── TODO.md                      # Feladatlista és roadmap
├── ARCHITECTURE_PLAN.md         # Refaktorálási és multi-agent terv
├── README.md                    # Dokumentáció-index (docs/00-18)
├── docs/                        # Részletes műszaki dokumentációk (00-18)
├── docker/                      # Fő repó konténerei (hesai_bridge, web_dashboard, mapping, mock_robot, realsense_bridge, rosbridge, webrtc_bridge, mc_motion, mc_sensor_hub, dev)
├── mission-control/             # 9-pilléres operátori rendszer (önálló al-modul, saját dokumentáció)
│   ├── PROJECT_BRIEF.md         #   teljes szerep+kontextus sablon, "honnan vegye át egy jövőbeli munkamenet"
│   ├── STATUS.md                #   futtatási referencia (mock/live módok, gyors parancsok)
│   ├── CONVENTIONS.md           #   MÉRVADÓ minden pillérnek: portok, robot-kliens import, event bus, Dockerfile-minta
│   ├── AUDIT-2026-09-10.md      #   biztonsági audit + 12 P0 hiba (mind javítva)
│   ├── core/                    #   robot-kliens absztrakció (mock/live/remote)
│   └── <pillér>/                #   mapping, navigation, orchestration, sensors, multicam, audio, blackbox, remote, digital-twin — mindnek saját README.md
├── xavier-pickerbot/             # Testvér-robot dokumentáció + saját irányítópult/akadémia terv
├── foxglove/                     # Foxglove Studio layout
└── backups/                      # Konfig-pillanatképek (nem teljes lemezkép)
```

**Agent-olvasási szabály (token-spórolás):** egy pilléren dolgozó ágens csak a saját
pillér `README.md`-jét + `mission-control/CONVENTIONS.md`-t olvassa el — **nem** a teljes
`AUDIT`/`PROJECT_BRIEF` fájlokat. Azok csak új munkamenet-indításkor, teljes kontextus
felvételéhez kellenek. Ld. [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md) 4. szakasz.

---

## 3. Core Rules & Constraints (Szigorú Szabályok az AI számára)

> [!CAUTION]
> **[Klón: C:SERSSERNERO_GO2 � SLAM/DOCS áG]**
> **BIZTONSÁGI ALAPSZABÁLY:** A robot fizikai biztonsága az első! Soha ne futtass ismeretlen mozgásparancsot a roboton anélkül, hogy a fizikai robot vészleállítója / távirányítója kéznél lenne.

1. **Natív Rendszer Védelem:** A Jetson Orin natív gyári rendszerébe (`/unitree`, `/opt/ros`, netplan) **TILOS közvetlenül telepíteni**! Minden új modul kizárólag **Docker-konténerben** futhat.
2. **Kódmódosítási Szabály:** Kódmódosításkor **CSAK a megváltozott részeket (diff)** mutasd a felhasználónak, soha ne generáld újra a teljes fájlt indokolatlanul.
3. **Adatvesztési Tilos:** A LiDAR pontfelhő szűrésnél a 0% pont-törlés elvét követjük — a pontok összeolvasztása engedélyezett, de strukturális pontok törlése tiltott.
4. **Hálózati IP-k és Portok (Fixek, módosítani tiltott):**
   - Jetson Orin: `192.168.123.18` (SSH: `unitree:123`, port 22)
   - Robot MCU: `192.168.123.161`
   - Hesai LiDAR: `192.168.123.20`
   - Fejlesztői gép: `192.168.123.99`
   - Dashboard Port: `5002`
   - SLAM Workbench Port: `8080` / `8088`
5. **Kódstílus:** Mentes a felesleges magyarázatoktól. Tiszta, moduláris, jól dokumentált Python és Vanilla JS kód.
> **[Klón: C:devNERO_GO2 — mission-control ág]**
> **BIZTONSÁGI ALAPSZABÁLY:** A robot fizikai biztonsága az első! Soha ne futtass ismeretlen
> mozgásparancsot a roboton anélkül, hogy a fizikai vészleállító/távirányító kéznél lenne.
> Mozgásparancsot (`robot.move(...)`) csak akkor küldj, ha `robot.is_armed()` igaz.

1. **Natív Rendszer Védelem:** A Jetson Orin gyári rendszerébe (`/unitree`, `/opt/ros`, netplan) **TILOS közvetlenül telepíteni**! Minden új modul kizárólag **Docker-konténerben** futhat.
2. **Kódmódosítási Szabály:** Kódmódosításkor **CSAK a megváltozott részeket (diff)** mutasd, soha ne generáld újra a teljes fájlt indokolatlanul.
3. **Robot-elérés csak a `core` absztrakción át:** soha ne hívj DDS-t vagy `webrtc_bridge`-et közvetlenül egy pillérből — mindig `from robot_client import get_robot_client` (ld. CONVENTIONS.md).
4. **Adatvesztési Tilos:** LiDAR pontfelhő szűrésnél 0%-os pont-törlés elve — összeolvasztás engedélyezett, strukturális pont törlése tiltott.
5. **Hálózati IP-k és Portok (Fixek, módosítani tiltott):**

   | | |
   |---|---|
   | Jetson Orin | `192.168.123.18` (SSH: `unitree`/`123`, port 22) |
   | Robot MCU | `192.168.123.161` |
   | Hesai LiDAR | `192.168.123.20` |
   | Fejlesztői gép | `192.168.123.99` |
   | Xavier Pickerbot Mini | `192.168.0.100` (**külön** hálózat, nem ugyanaz az alháló!) |

   | mission-control pillér | Port |
   |---|---|
   | core (debug/status) | 9101 |
   | mapping | 9102 |
   | navigation | 9103 |
   | orchestration | 9104 |
   | sensors | 9105 |
   | multicam | 9106 |
   | audio | 9107 |
   | blackbox | 9108 |
   | digital-twin (static viewer) | 9110 |
   | redis (event bus) | 6379 |
   | Fő repó web_dashboard | 5002 |
   | Fő repó SLAM Workbench | 8080 / 8088 |

6. **Env-változók (mock vs. live, ld. CONVENTIONS.md):** `ROBOT_BACKEND=mock\|live`, `ROBOT_CLIENT_MODE=local\|remote`, `CORE_URL`, `MC_API_TOKEN`.
7. **Kódstílus:** Mentes a felesleges magyarázatoktól. Tiszta, moduláris, jól dokumentált Python és Vanilla JS.
