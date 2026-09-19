# "Kövesd az embert" mód — YOLO-alapú személykövetés

**Státusz (2026-09-17): steering-matek + Flask-bekötés + unit tesztek
készek, MOCK_SDK-val végigtesztelve. Valódi kamerán/roboton még SOSEM
futott — ld. alul "Holnap reggeli teszt-terv", és ne kerülje meg senki ezt
a sorrendet.**

Kapcsolódó TODO-elem: [`TODO.md`](../TODO.md) "YOLO képfelismerés élesben,
roboton futtatva" (a testvér-klón `docker/realsense_bridge/yolo_detector.py`
prototípusáról).

## Mi készült el

- [`docker/realsense_bridge/yolo_detector.py`](../docker/realsense_bridge/yolo_detector.py)
  — a testvér-klón (`C:\Users\user\NERO_GO2`) prototípusának 1:1 átemelt
  másolata. Nem módosítottuk az API-ját (`detect(image, weights, conf_threshold)`
  -> `{"detections": [...], "count", "elapsed_ms"}`), csak most már ebben a
  klónban is elérhető, hogy a `web_dashboard` importálhassa.
- [`docker/web_dashboard/person_follow.py`](../docker/web_dashboard/person_follow.py)
  — TISZTA, SDK/Flask/YOLO-független szabályozó-matek (ugyanaz a minta,
  mint `app.py` `compute_nav_command`/`compute_tracking_command`-je):
  - `pick_person_target(detections)` — a legnagyobb bbox-területű,
    `FOLLOW_MIN_CONFIDENCE` (0.45) felett detektált "person" kiválasztása.
  - `compute_follow_command(bbox, frame_width, frame_height)` — bbox
    vízszintes eltolása a kép közepétől → `vyaw`; bbox-magasság a
    kép-magasság hányadaként (távolság-proxy) → `vx`. Korlátok:
    `FOLLOW_MAX_VX = 0.4 m/s`, `FOLLOW_MAX_VYAW = 0.8 rad/s` — óvatosabb,
    mint a joystick (`MOVE_SPEED=0.5`), mert itt a cél (az ember) is
    kiszámíthatatlanul mozoghat. Sosem megy hátra automatikusan (ha a
    személy "túl közel" van a bbox-méret alapján, egyszerűen megáll).
  - `person_lost(last_seen_ts, now_ts, timeout_s=2.0)` — explicit
    időparaméterekkel, hogy a teszt determinisztikus legyen (nincs valódi
    `time.sleep`).
- `docker/web_dashboard/app.py` bekötés:
  - `_FakeSportClient.StopMove()` — a mock SDK-hoz hozzáadva (a valós
    `unitree_sdk2py` SportClient-nek van dedikált `StopMove()` hívása a
    Move()-sebesség lenullázásához; ha valamiért nem lenne elérhető,
    `_safe_stop_move()` visszaesik a kódbázisban máshol is használt
    `Move(0,0,0)`-ra — sosem dob kifelé kivételt).
  - `_follow_thread()` — a tényleges vezérlő szál: kameraképet kér a
    `webrtc_bridge`-től (`WEBRTC_BRIDGE_URL/camera.jpg`, ugyanaz a minta,
    mint `_capture_photo()`), lusta importtal betölti a YOLO-detektort
    (`_load_yolo_detect()`, csak ekkor importálja az `ultralytics`-ot —
    így a dashboard `ultralytics`/`cv2` nélkül is elindul, ha valaki csak
    UI-t fejleszt), lefuttatja a detekciót, kiszámolja a parancsot, és
    **KIZÁRÓLAG** a meglévő `sport_client.Move()`-on keresztül küldi ki —
    nincs itt semmilyen új, hardver felé közvetlen parancsút (nincs
    `LowCmd`, nincs joint-szintű írás). Minden tick hívja `_touch_activity()`-t,
    amíg tényleg mozgásparancsot küld, hogy a P0 watchdog (ld.
    `mission-control/tests/test_watchdog.py` minta, itt a `_watchdog()`
    függvény) ne dobja le a fegyverzett állapotot aktív követés közben.
    Ha >2 mp-ig nincs "person" detekció, `_safe_stop_move()`-ot hív és
    naplóz, nem megy tovább "vakon".
  - Új route-ok: `POST /api/follow/start` (armed-kapu mögött, 403 ha
    nincs élesítve), `POST /api/follow/stop`, `GET /follow_status`
    (JSON: `active`, `detected`, `bbox`, `confidence`, `vx`, `vyaw`,
    `last_event`).
  - `/api/estop` mostantól a `follow` állapotot is nullázza (ugyanúgy,
    mint a `security` módot) — a vészleállító minden futó autonóm
    scriptet megszakít, a "kövesd az embert" módot is beleértve.
- [`docker/web_dashboard/tests/test_person_follow.py`](../docker/web_dashboard/tests/test_person_follow.py)
  — 18 unit teszt, mind zöld, a `mission-control/tests/test_watchdog.py`
  stílusát követve (sima assert-ek, nincs mock-keretrendszer). Lefedi:
  - `pick_person_target`: nem-"person" osztály kizárása, alacsony
    konfidencia kizárása, legnagyobb bbox kiválasztása, üres/`None` lista.
  - `compute_follow_command`: középre állt + célméretű személynél nulla
    parancs, balra/jobbra dőlt bbox helyes fordulási irány, holtzóna,
    közeli/távoli személy előre-menés iránya (sosem hátra), `vx`/`vyaw`
    korlátok szélsőséges bemenetnél, nulla képméret kezelése (nincs
    osztás-nullával hiba).
  - `person_lost`: sosem-látott eset, időn belüli/időn túli eset, egyedi
    timeout, pontos határeset.
  - Futtatás: `cd docker/web_dashboard && python -m pytest tests/test_person_follow.py -q`
    → **18 passed**. A teljes `tests/` mappa (a meglévő
    `test_joint_safety.py`-vel együtt) is zöld: **62 passed**.

## Mi HIÁNYZIK még (nem áltatjuk magunkat)

- **`ultralytics` sosem futott ezen a gépen/roboton valódi képpel.** A
  fejlesztői gépen nincs telepítve (`ModuleNotFoundError` — szándékosan
  csak lusta importtal derül ki, `/api/follow/start`-nál, ld. lentebb a
  hibakezelést), a `requirements.txt`-be felvettük, de a tényleges
  detekciós pontosság/sebesség Jetsonon **nem ellenőrzött**.
- **Valódi kamera-frame sosem ment át a pipeline-on.** MOCK_SDK-val a
  `webrtc_bridge` sem fut, így a `_follow_thread()` minden tick-en
  "nincs kép" ágra esik, és a "nincs személy → 2 mp után állj" logikát
  teszteltük élesben — a "van személy → kövesd" ágat **csak** a pure
  unit tesztek fedik, valódi YOLO-kimeneten még nem.
- **Az Intel RealSense USB hardver-hiba (`RS2_USB_STATUS_PIPE`)**
  továbbra is megoldatlan (ld. `TODO.md` "Rövid Távú Feladatok") — ha a
  holnapi teszt a RealSense-en (nem a robot fő webrtc-kameráján) menne
  keresztül, ez elsőként blokkolhat. A `_follow_thread()` jelenleg a
  **fő `webrtc_bridge` kamerát** használja (`WEBRTC_BRIDGE_URL/camera.jpg`,
  ugyanazt, amit a `/camera_feed` és `_capture_photo()` is), NEM a
  RealSense-t — ezért ez a hiba **nem** feltétlenül blokkolja a holnapi
  tesztet, csak ha külön RealSense-alapú követésre váltanánk.
- Nincs teszt arra, hogy két egyidejű `/api/follow/start` hívás
  (verseny-helyzet) mit csinál — a kód `_follow_lock`-kal védi az
  `active` flaget és no-op-ot ad vissza másodikra, de ez explicit unit
  teszttel nincs lefedve.

## Holnap reggeli teszt-terv

1. **Előbb MOCK_SDK=1, kamera nélkül (ma este ez már megtörtént):**
   ```bash
   cd docker/web_dashboard
   MOCK_SDK=1 python app.py
   ```
   Böngészőben `/`, élesítés (`Arm`), majd:
   ```bash
   curl -X POST http://localhost:5002/api/follow/start
   curl http://localhost:5002/follow_status
   curl -X POST http://localhost:5002/api/follow/stop
   ```
   Elvárt: `active: true` utána `error: yolo unavailable` a `last_event`-ben,
   *ha* `ultralytics` nincs telepítve — ez NEM hiba, ez a dokumentált
   lusta-import védőháló. `pip install ultralytics` után újraindítva a
   `last_event.type` már nem `error`.

2. **`ultralytics` telepítése + statikus tesztkép (még mindig nem a
   robot):**
   ```bash
   pip install ultralytics
   python -c "from yolo_detector import detect; print(detect('valami_kep_egy_emberrel.jpg'))"
   ```
   (a `docker/realsense_bridge` mappából, vagy a `sys.path`-hoz hozzáadva,
   ld. `_load_yolo_detect()` app.py-ban) — ellenőrizni, hogy a
   `yolov8n.pt` súlyfájl letöltődik és a JSON-kimenet tartalmaz
   `"class": "person"` bejegyzést egy emberes képen.

3. **CSAK EZUTÁN, felügyelettel, nyílt téren, valós kamerával:**
   - `WEBRTC_BRIDGE_URL` álljon a valódi `webrtc_bridge`-re, a robot
     kamerája adjon valós JPEG-et a `/camera.jpg`-n.
   - Élesítés + `/api/follow/start` — **valaki tartsa kézben az
     E-stop-ot** (`/api/estop` gomb a dashboardon, vagy fizikai gomb),
     amíg a mód aktív.
   - Nézni: a `/follow_status` `bbox`/`confidence`/`vx`/`vyaw` mezőit
     valós időben, és hogy a robot valóban a detektált személy felé
     fordul/halad, konzervatív sebességgel.
   - Elsőre **NE** engedjünk a robotnak közel menni valós emberhez — a
     teszt-személy maradjon 2+ méterre, és bárki azonnal E-stopolhasson.

## Biztonsági megjegyzések (ISMÉTELVE, mert ez a lényeg)

- **Ez a mód a robotot TÉNYLEGESEN egy ember felé mozgatja, felügyelet
  nélkül, amíg aktív.** Csak akkor futtassuk, ha valaki figyeli és az
  E-stop (`/api/estop`, vagy fizikai gomb) kézközelben van.
- Csak **nyílt, akadálymentes térben** teszteljük — ennek a módnak
  **nincs** akadálykerülése (nem néz LiDAR-t/mélységet, csak a YOLO
  bbox-ot), ld. `docs/16-mission-control-terv.md` és a
  `project_go2_mission_control_audit_2026-09-10` feljegyzés hasonló
  figyelmeztetését a lépcső-heurisztikára — itt ugyanez a kockázati
  osztály: egy 2D képalapú vezérlés vak a 3D akadályokra.
- A sebesség-korlátok (`FOLLOW_MAX_VX=0.4`, `FOLLOW_MAX_VYAW=0.8`)
  szándékosan a legóvatosabb sávban vannak a kódbázis összes mozgás-
  módja között — ha a teszt során ez is túl gyorsnak bizonyul,
  csökkentsük tovább `person_follow.py`-ban, NE a hívó oldalon.
- A vezérlés kizárólag a meglévő, watchdog/E-stop-védett
  `sport_client.Move()`-on megy át — nincs és nem is szabad lennie
  külön, védtelen parancsútnak ehhez a módhoz.
