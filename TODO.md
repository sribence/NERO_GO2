# 🗺️ NERO GO2 — Projekt Roadmap & TODO

Ez a dokumentum tartalmazza a korábbi munkamenetek, mérések és megbeszélések alapján felhalmozott, még elvégzésre váró feladatokat.

---

## 🚨 1. Azonnali Feladatok (Immediate / High Priority)

- [ ] **Éles LiDAR adatáram csatlakoztatása (`run_kiss_icp.py`):**
  - A felvett adatsorok (`walk_kicsi.jsonl`, `walk_seta1.jsonl`) után az élő Hesai UDP adatfolyam bekötése a választott KISS-ICP odometriai motorba a `hesai_bridge.py`-on keresztül.
- [ ] **RealSense D435i kamerakép és Depth Stream integráció:**
  - A `nero_go2_realsense_bridge` konténer élő videóstreamjének ellenőrzése és megjelenítése a Web Dashboardon (`:5002`).
- [ ] **Térkép mentési & exportáló modul:**
  - Az elkészült 3D pontfelhő térképek exportálása szabványos **PLY**, **PCD** és **2D OctoMap Grid** formátumokba.

---

## ⏱️ 2. Rövid Távú Feladatok (Short-Term Roadmap)

- [ ] **2D Occupancy Grid térkép generálás a 3D KISS-ICP pontfelhőből:**
  - A robot navigációjához szükséges 2D akadálytérkép valós idejű vágása a 3D LiDAR adatokból (magassági szeleteléssel).
- [ ] **Joystick & Webes Mozgásvezérlés éles tesztje:**
  - Biztonságos parancsküldés a webes felületről a `rt/sportmodecmd` csatornán keresztül (állj, ülj, séta, sebességvektorok).
- [ ] **Intel RealSense finom felületek integrálása:**
  - A sűrű RealSense mélységadatok ráillesztése a Hesai LiDAR által kiépített globális vázra (multi-sensor registration).
- [ ] **Teljes lemezkép-mentés (Jetson Orin NVMe/eMMC):**
  - Biztonsági klón készítése a Jetson dokk teljes lemezéről.

---

## 🔭 3. Hosszú Távú Feladatok (Long-Term / Advanced Vision)

- [ ] **Autonóm Waypoint Navigáció:**
  - Két pont kijelölése a webes 3D/2D térképen és az autonóm útvonaltervező (`/follow_waypoints`) végrehajtása.
- [ ] **AI Objektumkövetés (YOLOv8 + PID):**
  - Objektum-kijelölés a kameraképen (pl. doboz/személy követése) a Jetson GPU gyorsításával (`tegrastats` monitorozás mellett).
- [ ] **Ágens-Alapú Autonóm Hangolás:**
  - LLM / AI Ágens felhatalmazása a SLAM paraméterek (voxel méret, szűrők) automatikus korrekciójára a mért fal-RMS hiba alapján.
- [ ] **Oktatási bemutató csomag:**
  - Diákoknak szóló demonstrációs felület, forgatókönyv és hibaelhárítási cheat-sheet véglegesítése.
