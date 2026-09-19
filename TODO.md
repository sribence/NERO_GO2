> **[Klón: C:SERSSERNERO_GO2 � SLAM/DOCS áG]**
# 🗺️ NERO GO2 — Projekt Roadmap & TODO

Ez a dokumentum tartalmazza a korábbi munkamenetek, mérések és megbeszélések alapján felhalmozott, még elvégzésre váró feladatokat.
> **[Klón: C:devNERO_GO2 — mission-control ág]**
# 🗺️ NERO GO2 (dev/mission-control) — Projekt Roadmap & TODO

Ez a dokumentum a `C:\dev\NERO_GO2` klón (mission-control ág) még elvégzésre váró
feladatait tartalmazza. A testvér-klón (`C:\Users\user\NERO_GO2`, SLAM/docs ág) saját
külön TODO.md-vel rendelkezik.

---

## 🚨 1. Azonnali Feladatok (Immediate / High Priority)

> **[Klón: C:SERSSERNERO_GO2 � SLAM/DOCS áG]**
- [ ] **Éles LiDAR adatáram csatlakoztatása (`run_kiss_icp.py`):**
  - A felvett adatsorok (`walk_kicsi.jsonl`, `walk_seta1.jsonl`) után az élő Hesai UDP adatfolyam bekötése a választott KISS-ICP odometriai motorba a `hesai_bridge.py`-on keresztül.
- [ ] **RealSense D435i kamerakép és Depth Stream integráció:**
  - A `nero_go2_realsense_bridge` konténer élő videóstreamjének ellenőrzése és megjelenítése a Web Dashboardon (`:5002`).
- [ ] **Térkép mentési & exportáló modul:**
  - Az elkészült 3D pontfelhő térképek exportálása szabványos **PLY**, **PCD** és **2D OctoMap Grid** formátumokba.
> **[Klón: C:devNERO_GO2 — mission-control ág]**
- [ ] **Docker Compose teljes stack (9 konténer) blokkolva:**
  - WSL2 / "Virtual Machine Platform" Windows-funkció engedélyezése (admin + restart) ezen a fejlesztői gépen. Amint kész, a `docker compose up --build` változtatás nélkül futtatható.
- [ ] **`ROBOT_BACKEND=live` teljes út élő roboton sosem futott:**
  - 2 telemetria-mezőnév (`LiveRobotClient`) ellenőrizése/egyeztetése a valódi `webrtc_bridge` API-val, első élő mozgásteszt előtt.
- [ ] **`rosbridge_suite` SIGSEGV `network_mode: host`-on:**
  - Vagy megoldás, vagy dokumentáltan lezárva véglegesen (a `mission-control` már tudatosan WebRTC+DDS-re épül helyette).

---

## ⏱️ 2. Rövid Távú Feladatok (Short-Term Roadmap)

> **[Klón: C:SERSSERNERO_GO2 � SLAM/DOCS áG]**
- [ ] **2D Occupancy Grid térkép generálás a 3D KISS-ICP pontfelhőből:**
  - A robot navigációjához szükséges 2D akadálytérkép valós idejű vágása a 3D LiDAR adatokból (magassági szeleteléssel).
- [ ] **Joystick & Webes Mozgásvezérlés éles tesztje:**
  - Biztonságos parancsküldés a webes felületről a `rt/sportmodecmd` csatornán keresztül (állj, ülj, séta, sebességvektorok).
- [ ] **Intel RealSense finom felületek integrálása:**
  - A sűrű RealSense mélységadatok ráillesztése a Hesai LiDAR által kiépített globális vázra (multi-sensor registration).
- [ ] **Teljes lemezkép-mentés (Jetson Orin NVMe/eMMC):**
  - Biztonsági klón készítése a Jetson dokk teljes lemezéről.
> **[Klón: C:devNERO_GO2 — mission-control ág]**
- [ ] **YOLO képfelismerés élesben, roboton futtatva:**
  - Kész prototípus a testvér-klónban: `docker/realsense_bridge/yolo_detector.py` (ultralytics YOLOv8, bbox+class+confidence JSON kimenet) — Jetsonon sosem futott élesben.
  - Bekötendő a `mission-control/sensors` vagy `multicam` pillérbe, RealSense/kamera streamre. Ellenőrizni: felismerési pontosság, Jetson GPU/hő terhelés (`tegrastats`).
  - Referencia terv: `docs/11-oktatocsomag-terv.md` Fázis 4, `docs/12-taszklista.md`.
- [ ] **Xavier Pickerbot Mini bekötése a mission-control orchestration-be (azonos szintű integráció):**
  - Cél: a Xavier ugyanolyan szintű `mission-control` lefedettséget kapjon, mint a Go2 (jelenleg csak saját, elszigetelt irányítópultja van, `xavier-pickerbot/docs/05`).
  - Előfeltétel a lenti "multi-robot `core` refaktor" — anélkül a Xavier csak egy második, párhuzamos, nem összekötött stack maradna.
- [ ] **2D Occupancy Grid finomítás + `level_id` cellánkénti (nem csak map-szintű) címkézés** a többszintes térképezéshez.
- [ ] **Intel RealSense USB hardver-hiba (`RS2_USB_STATUS_PIPE`) megoldása** vagy másik port/kábel beszerzése — jelenleg parkoltatva.

---

## 🔭 3. Hosszú Távú Feladatok (Long-Term / Advanced Vision)

> **[Klón: C:SERSSERNERO_GO2 � SLAM/DOCS áG]**
- [ ] **Autonóm Waypoint Navigáció:**
  - Két pont kijelölése a webes 3D/2D térképen és az autonóm útvonaltervező (`/follow_waypoints`) végrehajtása.
- [ ] **AI Objektumkövetés (YOLOv8 + PID):**
  - Objektum-kijelölés a kameraképen (pl. doboz/személy követése) a Jetson GPU gyorsításával (`tegrastats` monitorozás mellett).
- [ ] **Ágens-Alapú Autonóm Hangolás:**
  - LLM / AI Ágens felhatalmazása a SLAM paraméterek (voxel méret, szűrők) automatikus korrekciójára a mért fal-RMS hiba alapján.
- [ ] **Oktatási bemutató csomag:**
  - Diákoknak szóló demonstrációs felület, forgatókönyv és hibaelhárítási cheat-sheet véglegesítése.
> **[Klón: C:devNERO_GO2 — mission-control ág]**
- [ ] **Multi-robot `core` refaktor (Xavier + Go2 közös "küldetés" felület):**
  - `mission-control/core/service.py` bontása több robot-példányra: `/robots/{id}/state`, minden pillér `ROBOT_ID` env-változóval megkülönböztetve.
  - Alap: `AUDIT-2026-09-10.md` 9.6 szakasza + `README.md` "6. ötlet". Idézet: "architektúra és API 100%-ban [megcsinálható robot nélkül]; a valós együttműködés nem."
  - Ez az előfeltétele a fenti Xavier-integrációnak.
- [ ] **Új pózok / trükkök betöltése és rátöltése a robotra (pl. szaltó):**
  - **Kutatás szükséges először:** jelenleg a mozgásvezérlés kizárólag a gyári `SportClient` magas szintű hívásain megy (`Move`, `RecoveryStand`, `StandDown`, `Hello`, `Heart`, `Sit`) — nincs `FrontFlip`/`BackFlip`/trükk-parancs sehol a kódban. Ellenőrizni, hogy az `unitree_sdk2py` SportClient natívan támogat-e ilyen névvel ellátott mozdulatokat, vagy csak alacsony szintű (`LowCmd`) trajektória-feltöltéssel érhető el.
  - A `web_dashboard`-ban látott `_pose_stand`/`_pose_walk`/`_pose_wave`/`_pose_sit`/`_pose_bow` (docker/web_dashboard/app.py:737) **csak a 3D digitális iker vizuális animációja**, kézzel kitalált szögekkel — **nem** valódi robot-vezérlés, ne keverjük össze a két feladatot.
  - Safety-kritikus: fizikai teszt előtt vészleállító + fokozott óvatosság (ld. Core Rules).
- [ ] **Robot csuklóinak (hip/thigh/calf) külön-külön, kézi vezérlése:**
  - Jelenleg nincs joint-szintű (`LowCmd`) kézi vezérlési felület — csak a magas szintű `SportClient.Move()` létezik.
  - **2026-09-17: safety-réteg elkészült, robotra még nem ment.** `docker/web_dashboard/joint_safety.py` (`JointSafetyManager`) — pozíció (URDF+5° margin), per-tick rate limit (3°), kp/kd cap, tau/effort cap. 13 unit teszt zöld (`docker/web_dashboard/tests/test_joint_safety.py`). Doksi + holnapi robotos teszt-eljárás: [docs/17-joint-szintu-kezi-vezerles-biztonsag.md](docs/17-joint-szintu-kezi-vezerles-biztonsag.md).
  - **Még hiányzik:** tényleges `LowCmd` publish útvonal (API mezőnevek forrásból ellenőrizendők, ne kitalálva), watchdog-integráció ehhez az útvonalhoz, operátori UI-panel (nem a meglévő joystick).
  - Erősen safety-kritikus — csak a P0 biztonsági réteg (watchdog, E-stop, sebességkorlát — már megvan a fő mozgáshoz) mellé, azzal analóg védelemmel szabad megépíteni.
- [ ] **Autonóm Waypoint Navigáció + ismétlődő őrjárat, geofencing, változás-detektálás** (README.md 1-5. ötletek).
- [ ] **Auth/RBAC a Tailscale-en át érkező hozzáférésekhez** (README.md 9. ötlet).
- [ ] **Web-es incidens-visszanéző UI a blackboxhoz + szimuláció/replay mód.**
- [ ] **Valódi relokalizáció (ICP scan-match)** a `digital-twin` konfidencia-jelzőjéhez (jelenleg szimulált/fix érték).
- [ ] **A két elágazott klón (`C:\dev\NERO_GO2` és `C:\Users\user\NERO_GO2`) egyesítése és push GitHub-ra.**
