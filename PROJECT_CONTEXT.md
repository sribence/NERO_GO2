# 🤖 NERO GO2 — AI Project Context & Operational Rules

## 1. Project Overview
A **NERO GO2** projekt célja a Unitree Go2 Edu négylábú robot és a rá szerelt szenzorok (Hesai PandarXT-16 3D LiDAR, Intel RealSense D435i, robot IMU) adatainak integrálásával egy valós idejű, robot-odometriától független, szoba- és épületszintű 3D SLAM térképező és autonóm navigációs rendszer kiépítése.

### Komponensek és Ágensek kapcsolódása:
- **Alacsony szintű mozgásvezérlés (MCU):** `192.168.123.161` — CycloneDDS kommunikáció a robot láb/motor rendszere felé.
- **Fedélzeti számítási egység (Jetson Orin Dokk):** `192.168.123.18` — Ubuntu Linux, Docker konténerekben futó szolgáltatások.
- **LiDAR Szenzor:** Hesai PandarXT-16 (`192.168.123.20`), UDP pontfelhő adatfolyam (360° FOV, 16 csatorna).
- **Web Dashboard & digitális iker:** Flask backend + SSE + Vanilla JS / Three.js 60 FPS WebGL felület (`:5002`, `:8080`, `:8088`).
- **AI Ágensek szerepe:** Autonóm állapotfelmérés, feladattervezés, pontfelhő-feldolgozási paraméterek dinamikus hangolása és felületkezelés.

---

## 2. Current Stack & Architecture

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

---

## 3. Core Rules & Constraints (Szigorú Szabályok az AI számára)

> [!CAUTION]
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
