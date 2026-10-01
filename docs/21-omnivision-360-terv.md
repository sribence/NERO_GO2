# OmniVision 360 — körkamerás, LiDAR-fúziós, emberkerülő felfedező modul

**Branch:** `feature/omnivision-360` (NERO_GO2). Submodule-okban azonos nevű branch, amikor ott kód készül.
**Státusz (2026-10-01):** terv. Kód nincs. Hardver (4 kamera) nincs felszerelve.
**Cél:** futurisztikus, játékszerű irányítómodul a Go2-höz, amely Jetson Orin NX-en (JetPack 5.1.1) fut és GPU-takarékos.

---

## 0. Összefoglaló

| Képesség | Megoldás egy mondatban |
|---|---|
| 360° nézet | 4 halszem-kamera képe; a varrást (stitch) a **böngésző GPU-ja** végzi egy three.js „tál” (bowl) felületen, nem a Jetson |
| Kutya 3D modell középen | meglévő `go2_description` URDF + `.dae` mesh-ek, élő ízületi szögekkel animálva |
| LiDAR vetítés + RGB pontok | XT16 pontok vetítése a kalibrált kamerákba → szín mintavétele → 5 cm-es színes voxeltérkép |
| Térpont-nézet (RGB) | folyamatosan épülő színes voxelfelhő, delta-streamként a böngészőbe |
| Emberek minden irányban | YOLO TensorRT INT8, mind a 4 kamera egy batch-ben, a távolságot a LiDAR adja (nem kell RealSense) |
| Folyamatos térképezés | meglévő `mapping` pillér (frontier-felfedezés, log-odds grid) + pose a LiDAR-odometriából |
| Emberkerülés (KRITIKUS) | emberekre „social costmap” + mozgáspredikció + független `safety_guard` sebességkorlátozó minden mozgásforrás és az `mc_motion` között |
| Jövő | hő-/IR-kamera (éjszakai mód), forgatható irányított mikrofon / mikrofontömb (hangforrás a 3D térképen) |

**Fő hatékonysági elvek (Jetson véges):**
1. Nincs CPU-s JPEG-dekódolás, nincs CPU-s remap. Csak a HW-blokkokat használjuk: NVJPG/NVDEC, NVENC, VIC/VPI, TensorRT.
2. Nincs teljes felbontású panoráma a roboton. A panorámát a kliens GPU-ja rakja össze.
3. Egy GPU-folyamat végzi a rögzítést, a detektálást és a színezést; a képkockák nem mennek keresztül Redisen vagy HTTP-n (unified memory, zero-copy).
4. Minden modulnak fix Hz-büdzséje van, a terhelés adaptívan csökkenthető (lásd 9. fejezet).

---

## 1. Hardver

### 1.1 Kamerák (4 db, körben)
- [ ] **HW-1** Kameratípus kiválasztása. Követelmény: ≥ 180° HFOV halszem (4 × 90° + átfedés a varráshoz és a kalibrációhoz), ≥ 1280×960, ≥ 20 fps, jó fényérzékenység (IMX462/IMX290/IMX678 osztály). Ha lehet: **global shutter** vagy legalább külső trigger-bemenet.
- [ ] **HW-2** Interfész döntése (sorrendben, ajánlottal kezdve):
  1. **GMSL2 4-csatornás kit** (deserializerrel, Orin NX-kompatibilis carrierrel): hosszú kábel, HW-szinkron, nincs USB-sávszél-gond. Drágább.
  2. **MIPI CSI** (ha a carrier ad 4 sávot / 4 portot): olcsóbb; ellenőrizni kell, hány CSI port van a jelenlegi dokkon.
  3. **USB3 UVC MJPEG** (4 kamera, 2 külön USB-vezérlőn): legolcsóbb, de az MJPEG-et NVJPG-vel kell dekódolni, és nincs HW-szinkron.
- [ ] **HW-3** Konzol / tartó tervezése (3D nyomtatás): a 4 kamera 0°/90°/180°/270° yaw szögben, azonos magasságban, kissé lefelé döntve (~10–15°), hogy a robot közvetlen környezete és a talaj is látszódjon. Rezgéscsillapítás (gumi alátét). Az XT16 látómezejét nem takarhatja.
- [ ] **HW-4** Áramfelvétel és -ellátás: 4 kamera + deserializer fogyasztása a Go2 akkuról (BMS-limit); DC-DC és biztosíték.
- [ ] **HW-5** Időszinkron: a kamerák trigger-jele a Jetson GPIO/PWM-ről (ha van trigger-bemenet). Az XT16 PTP-n a Jetson órájához (a `ptp4l` master a Jetsonon).
- [ ] **HW-6** USB/CSI sávszélesség-mérés: 4 stream egyszerre, 30 perc, dropped-frame számlálóval.

### 1.2 Meglévő szenzorok
- Hesai **PandarXT-16** (`hesai_bridge`): fő 3D-forrás, 10 Hz.
- Go2 beépített **L1 LiDAR** (`utlidar/cloud`): közeli takarás, alacsony akadályok.
- RealSense D435i: a meglévő `perception` elöl tovább használhatja. Az új rendszer **nem** függ tőle.

### 1.3 Jövőbeli hardver (előkészítés most, beépítés később)
- [ ] **HW-F1** Hőkamera (pl. FLIR Lepton 3.5 / Boson 320 osztály): elöl és/vagy körben. Az adatmodellben a kamerának legyen `modality: rgb|thermal|nir` mezője már most.
- [ ] **HW-F2** NIR-kamera + 850/940 nm IR-megvilágító: éjszakai mód. Az RGB kamerák IR-cut szűrője kapcsolható legyen.
- [ ] **HW-F3** Forgatható irányított mikrofon (pan-servo) **vagy** mikrofontömb (4–16 csatorna). Az ajánlás a tömb: DOA-hoz nem kell mozgó alkatrész; a pan-servo a fókuszált hallgatáshoz jön mellé.

---

## 2. Szoftver-architektúra

### 2.1 Új és módosított komponensek

| Komponens | Repó / útvonal | Port | Új? | Feladat |
|---|---|---|---|---|
| `omni` | `go2-brain-logic/mission_control/omni/` | **9114** | ÚJ | GPU-folyamat: 4 kamera rögzítése, rektifikálás, YOLO multi-cam, LiDAR-színezés, voxel RGB-térkép, streamelés |
| `safety_guard` | `go2-brain-logic/mission_control/safety_guard/` | **9115** | ÚJ | ember-tudatos sebességkorlátozó; MINDEN mozgásparancs ezen megy át az `mc_motion` előtt |
| `mapping` | meglévő (9102) | — | bővül | social layer a griden, pose a LiDAR-odometriából, frontier-pontozásban az ember-költség |
| `navigation` | meglévő (9103) | — | bővül | A* social costtal + lokális tervező (DWA-lite) dinamikus emberekkel |
| `perception` | meglévő (9112) | — | marad | elöl, RealSense alapú követés; az `omni` person-trackjei kiegészítik |
| `digital-twin` | meglévő (9110) | — | bővül | **OmniView UI**: bowl-nézet, kutya 3D, RGB-felhő, emberek, HUD |
| `hesai_bridge` | `go2-hardware-bridge` | — | bővül | pontonkénti időbélyeg (deskew-hoz), PTP |
| config | `NERO_GO2/config/omni/` | — | ÚJ | kalibráció (`cameras.yaml`, `extrinsics.yaml`), büdzsék (`budget.yaml`) |

Portok → a `CONVENTIONS.md` port-táblájába felvenni (`9114 omni`, `9115 safety_guard`).

### 2.2 Adatfolyam

```
 4× kamera ──(GMSL/CSI/USB)──► omni.capture ──► NVMM/CUDA buffer (zero-copy)
                                     │
            ┌────────────────────────┼─────────────────────────┐
            ▼                        ▼                         ▼
   omni.rectify (VPI LUT)    omni.stream (NVENC H.264)   omni.colorize ◄── XT16 (deskewed) + pose
            │                        │                         │
            ▼                        ▼                         ▼
   omni.detect (TRT batch=4)   WebRTC / WS ──► böngésző    voxel RGB map ──► delta WS ──► böngésző
            │
            ▼
   omni.track (ByteTrack/cam) ──► global fusion (robot frame, LiDAR range) ──► mc.omni.persons
                                                                                    │
                       ┌────────────────────────────────────────────────────────────┤
                       ▼                                ▼                           ▼
              mapping (social layer)          navigation (lokális tervező)    safety_guard (vmax-korlát / STOP)
                                                                                    │
                                                                                    ▼
                                                                             mc_motion /move
```

### 2.3 Redis-csatornák (új)
- `mc.omni.persons`: `{t, persons:[{gid, x, y, z, vx, vy, conf, cams:[...], bbox_by_cam:{...}, modality}]}`, 10 Hz
- `mc.omni.health`: fps kameránként, dropped frames, GPU%, hőmérséklet, aktuális büdzsé-szint, 1 Hz
- `mc.omni.calib_status`: a kalibráció érvényessége, reprojekciós hiba
- `mc.safety.state`: `{level: CLEAR|SLOW|STOP, vmax, nearest_person_m, reason}`, 20 Hz
- `mc.core.anomaly`: kamera-kiesés, kalibráció-drift, túlmelegedés (meglévő csatorna)

Képkocka **soha** nem megy Redisen. Csak metaadat.

---

## 3. Kalibráció (mindennek az alapja — enélkül semmi nem kerül a jó térpontra)

- [ ] **CAL-1** Kamera-intrinzikák: halszem-modell (OpenCV `fisheye` / Kannala-Brandt). Eszköz: Kalibr vagy saját OpenCV-szkript AprilGrid/ChArUco táblával. Elfogadás: reprojekciós hiba < 0.5 px.
- [ ] **CAL-2** Kamera–kamera extrinzikák (a szomszédos átfedésekből) + kamera–IMU (Kalibr `cam-imu`, opcionális).
- [ ] **CAL-3** Kamera–LiDAR extrinzika kameránként. Első lépés célpont-alapú módszer (tábla + élek / síkillesztés), második lépés célpont nélküli finomítás (mutual information vagy él-illesztés felvett adaton). Elfogadás: < 1 px átlagos él-eltérés 5 m-en.
- [ ] **CAL-4** Időeltolás (kamera vs. LiDAR vs. odometria) becslése: forgás közbeni felvételen keresztkorreláció; a `extrinsics.yaml`-ba `t_offset_s` mezőként.
- [ ] **CAL-5** Kalibrációs fájlformátum: `config/omni/cameras.yaml` (cam_id, modality, model, K, D, felbontás) és `extrinsics.yaml` (`T_base_cam`, `T_base_lidar`, `t_offset_s`). Egyetlen forrás, minden modul innen olvas.
- [ ] **CAL-6** Kalibráció-ellenőrző eszköz: LiDAR-pontok rávetítése a 4 képre, PNG-be mentve, és a UI-ban is egy „calib overlay” kapcsolóval.
- [ ] **CAL-7** Drift-figyelés futás közben: élek egyezése LiDAR-mélységugrás vs. kép-gradiens; ha romlik → `mc.core.anomaly`.
- [ ] **CAL-8** A meglévő `perception` `CAM_*` extrinzikái (README szerint nincsenek mérve) is ugyanebből a folyamatból jöjjenek.

---

## 4. `omni` pillér (GPU-mag)

### 4.1 Váz
- [ ] **OM-1** Pillér-váz a `CONVENTIONS.md` szerint: `app.py` (FastAPI), `Dockerfile` (Jetson base: `l4t-jetpack` / `ultralytics:latest-jetson-jetpack5`, ugyanaz, mint a `perception`-é), `README.md`, `requirements.txt`, `logs/events.jsonl`.
- [ ] **OM-2** Modulstruktúra (tiszta, egységtesztelhető magok, mint a `mapping_core.py`):
  ```
  omni/
  ├── app.py              # FastAPI + szálak indítása
  ├── capture.py          # CameraSource interfész: GstSource | UsbSource | MockSource(videófájl)
  ├── camera_model.py     # fisheye projekció/unprojekció (numpy + torch), tisztán matek
  ├── rectify.py          # LUT-generálás (egyszer), GPU remap (VPI vagy torch grid_sample)
  ├── detect.py           # TensorRT batch-inferencia, model_manager újrahasznosítva a perceptionből
  ├── track.py            # ByteTrack kameránként + globális fúzió (robot frame)
  ├── colorize.py         # LiDAR→kamera vetítés, z-buffer, szín-mintavétel
  ├── voxel_map.py        # színes voxel hash (GPU), delta-export
  ├── stream.py           # NVENC H.264 → WebRTC / fallback JPEG-WS
  ├── budget.py           # adaptív Hz/felbontás szabályzó
  └── tests/
  ```
- [ ] **OM-3** `MockSource`: 4 felvett videó (vagy egy 360°-os videóból kivágott 4 halszem-nézet) + egy felvett XT16 `.jsonl` (`walk_kicsi.jsonl`) visszajátszása, szinkronban. **Robot nélkül minden fejleszthető legyen** (ARCHITECTURE_PLAN elv).

### 4.2 Rögzítés
- [ ] **OM-4** GStreamer pipeline kameránként: `nvarguscamerasrc` (CSI/GMSL) vagy `v4l2src ! nvv4l2decoder mjpeg=1` (USB) → `nvvidconv` → NVMM. **CPU-s dekódolás tilos.**
- [ ] **OM-5** Időbélyeg képkockánként (a szenzor ideje, nem az érkezési idő); kamerák közti eltérés mérése és logolása.
- [ ] **OM-6** Kamera-kiesés kezelése: újranyitás backoff-fal (a `perception/camera_recovery.py` mintájára); a többi kamera megy tovább, a UI-ban a kieső szektor szürke.

### 4.3 Rektifikálás (detektáláshoz)
- [ ] **OM-7** A halszem képből kameránként **egy hengeres (cylindrical) nézet**: ~100° HFOV × 60° VFOV, 640×384. Ezen fut a YOLO (a halszem-torzítás rontja a detektálást a széleken).
- [ ] **OM-8** A LUT egyszer generálódik a kalibrációból; GPU-remap VPI-vel (VIC/CUDA backend) vagy `torch.nn.functional.grid_sample`-lel. Elfogadás: 4 nézet < 3 ms.

### 4.4 Ember-detektálás minden irányban
- [ ] **OM-9** Modell: `yolov8n` vagy `yolo11n`, csak `person` osztály (+ opcionálisan állat/kerékpár), **TensorRT INT8**, batch=4, 640×384 bemenet. INT8 kalibráció saját felvételekből (500–1000 kép).
- [ ] **OM-10** Büdzsé: 4 nézet együtt ≤ 25 ms, 10 Hz → a GPU kb. 25%-a. Ha nem fér bele: a kamerák váltott (round-robin) feldolgozása, menetirányba eső kamera 10 Hz, a többi 5 Hz.
- [ ] **OM-11** Tracking kameránként ByteTrack-kel (a `perception/person_tracker.py` újrahasznosítva).
- [ ] **OM-12** **3D pozíció LiDAR-ral:** a bbox-ba eső, kamerába vetített XT16-pontokból a robusztus mélység (alsó 30% medián, földpontok kiszűrve). LiDAR-találat nélkül tartalék: a bbox alja + talajsík feltevés (talpponti becslés).
- [ ] **OM-13** Globális fúzió: a kameránkénti trackek a robot frame-be, majd az átfedési zónában (két kamera látja ugyanazt az embert) Hungarian-társítás távolság + megjelenés (`perception/appearance.py`) alapján → `gid`. Kalman (x, y, vx, vy) világ-frame-ben, ego-motion kompenzációval (`mc_motion /odom`).
- [ ] **OM-14** Kimenet: `mc.omni.persons` 10 Hz + `GET /persons`.
- [ ] **OM-15** Elfogadás: 4 ember körben, statikus robot, ≥ 95% recall 8 m-en belül, pozícióhiba < 0.3 m 5 m-en, `gid` stabil kameraváltáskor (ember körbesétál).

### 4.5 LiDAR-színezés és RGB-térpontfelhő
- [ ] **OM-16** XT16 deskew: pontonkénti időbélyeg (a `hesai_bridge` bővítése) + pose-interpoláció. Enélkül forgás közben „elmosódik” a színezés.
- [ ] **OM-17** Vetítés: minden ponthoz a legjobb kamera (a legközelebbi optikai tengely, a kép közepéhez közelebbi pixel előnyben), halszem-projekció GPU-n (torch), a képkocka-időbélyeghez illesztett pózzal.
- [ ] **OM-18** Takarás-kezelés: alacsony felbontású z-buffer kameránként (pl. 160×120); csak a z-buffer-mélység + tolerancia alatti pont kap színt. (Különben a fal mögötti pont a fal színét kapja.)
- [ ] **OM-19** Voxel-térkép: 5 cm-es voxel hash a GPU-n, voxelenként `xyz` (átlag), `rgb` (súlyozott futó átlag, a súly a távolsággal és a beesési szöggel csökken), `n_obs`, `last_seen`, `level_id`. Kapacitás-korlát (pl. 2 M voxel) + LRU-kiírás lemezre csempénként (`tile 10×10 m`).
- [ ] **OM-20** Delta-export: a 0.5 s alatt változott voxelek bináris csomagban (`Float32 xyz` + `Uint8 rgb`, opcionálisan quantizált Int16 xyz csempe-originnel), WebSocketen. Teljes snapshot csak csatlakozáskor (csempénként, LOD-dal).
- [ ] **OM-21** Mentés/export: PLY (színes) és PCD; a `TODO.md` „Térkép mentési & exportáló modul” pontja ezzel teljesül.
- [ ] **OM-22** Büdzsé: a színezés 5 Hz, ≤ 8 ms/frame GPU.
- [ ] **OM-23** Elfogadás: felvett séta után a PLY-ban a falak, ajtók és bútorok színe felismerhető, élszellemkép (ghosting) < 10 cm.

### 4.6 Streamelés a UI felé
- [ ] **OM-24** **1. fázis (egyszerű):** kameránként 640×480 JPEG NVJPG-encoderrel, WebSocketen, 10 fps. 4 × ~40 KB × 10 = ~1.6 MB/s. Tailscale-en is elmegy.
- [ ] **OM-25** **2. fázis (hatékony):** NVENC H.264 kameránként (vagy a 4 kép egy 2×2 mozaikban, egy streamként) → WebRTC. A `webrtc_bridge` tapasztalata / `webrtcbin` újrahasznosítható. Alacsonyabb sávszél és késleltetés.
- [ ] **OM-26** Stream-paraméterek a UI-ból állíthatók (fps, felbontás, ki/be kameránként), a `budget.py` korlátai között.

---

## 5. Térképezés és felfedezés

- [ ] **MAP-1** Pose-forrás: a `mapping` jelenleg `robot.get_pose()`-t használ (gyári odometria). Ehelyett KISS-ICP / small_gicp LiDAR-odometria (`go2-brain-logic/mapping/run_kiss_icp.py`, `run_small_gicp.py`) élőben, a `TODO.md` 1. pontja szerint. Kimenet: `mc.mapping.pose` 10 Hz.
- [ ] **MAP-2** Loop-closure / relokalizáció (a `TODO.md` „Valódi relokalizáció” pontja): scan-context vagy ICP a kulcsképekre. A hosszabb felfedezéshez kell, különben a térkép elcsúszik.
- [ ] **MAP-3** A 2D grid (`floor`/`walls`) ugyanabból a deskewed XT16 + L1 felhőből épül, mint a színes voxeltérkép, így a kettő konzisztens.
- [ ] **MAP-4** Új grid-réteg: `social` (0–255), a `mc.omni.persons` alapján, lecsengéssel (az ember elmegy → a költség 2–3 s alatt eltűnik). A wire-sémát a `CONVENTIONS.md`-ben bővíteni kell (opcionális mező, backward-compatible).
- [ ] **MAP-5** Frontier-pontozás bővítése: `score = távolság + w_social·ember-közelség + w_info·várható új terület`. Embertömegbe nem küld felfedezni.
- [ ] **MAP-6** Felfedezési módok: `explore` (robotporszívó-szerű teljes lefedés), `patrol` (mentett waypointok), `return_home` (alacsony akku / elveszett kapcsolat esetén).
- [ ] **MAP-7** Akku- és kapcsolat-figyelés: `< 25%` vagy `> 5 s` heartbeat-kiesés → `return_home` vagy helyben állás (konfigurálható).

---

## 6. Emberkerülés és biztonság (P0 — mindent megelőz)

### 6.1 Elvek
- Az ember elkerülése **nem** csak a tervező dolga: egy **független** `safety_guard` folyamat korlátozza a sebességet akkor is, ha a tervező hibázik.
- Fail-safe: ha a `safety_guard` nem kap friss person-adatot (> 0.3 s) vagy a kamerák > 1 szektora kiesik → `SLOW`; ha a LiDAR is kiesik → `STOP`.
- A `safety_guard` **nem** armol és **nem** indít mozgást; csak korlátoz vagy megállít. Az armolás joga továbbra is az operátoré.

### 6.2 Feladatok
- [ ] **SAF-1** `safety_guard` pillér (9115): bemenet a `mc.omni.persons` + LiDAR-közelség (bármilyen pont a lábmagasság–1.8 m sávban) + `mc_motion /odom`. Kimenet: `mc.safety.state` 20 Hz.
- [ ] **SAF-2** Zónák (ember esetén; a mozgásirányban megnyújtva):
  | Zóna | Távolság | Hatás |
  |---|---|---|
  | STOP | < 0.8 m | vx=vy=0, csak elfordulás az embertől távolodva |
  | SLOW | 0.8–2.0 m | vmax lineárisan 0.1 → 0.4 m/s |
  | CAUTION | 2.0–3.5 m | vmax 0.6 m/s, a tervező kerül |
  | CLEAR | > 3.5 m | normál |
- [ ] **SAF-3** Predikció: konstans sebességű modell 2 s horizonttal; ütközési idő (TTC) < 2 s → `SLOW`, < 1 s → `STOP`.
- [ ] **SAF-4** Bekötés: a `navigation`, a `mapping` (explore) és a `follow_executor` **mind** a `safety_guard /move` végpontjára küld; csak a `safety_guard` beszél az `mc_motion /move`-val. A watchdog-lánc megmarad (`mc_motion` 0.5 s).
- [ ] **SAF-5** Gyerek / gyorsan mozgó / eleső ember: magasság < 1.3 m vagy |v| > 2 m/s → zónák × 1.5.
- [ ] **SAF-6** Holttér-kezelés: ha a kamera nem lát (sötét, beégés), a LiDAR-klaszter „ember-szerű” (0.3–0.8 m széles, 1–2 m magas) objektumként számít → konzervatív.
- [ ] **SAF-7** Egységtesztek a döntési függvényre (`decide(persons, lidar_near, odom) → level, vmax`), a `follow_executor` `decide()` mintájára. Minden zónaátmenetre és fail-safe ágra.
- [ ] **SAF-8** Vészleállító a UI-ban: nagy, mindig látható STOP gomb (+ szóköz billentyű) a `safety_guard`-on át `mc_motion /stop`.
- [ ] **SAF-9** Fizikai teszt-protokoll dokumentálva (`docs/`): üres terem → 1 ember statikusan → 1 ember szembejön → 2 ember keresztez → „ugrás elé” bábuval. Minden lépés előtt E-stop próba.
- [ ] **SAF-10** Safety-review (ARCHITECTURE_PLAN: `safety_reviewer_prompt.md`) minden mozgást érintő diffen, merge előtt.

### 6.3 Lokális tervező
- [ ] **NAV-1** A* a `floor` + inflációs + `social` költséggel (a meglévő `astar.py` bővítése súlyozott költséggel).
- [ ] **NAV-2** Lokális tervező 10 Hz: DWA-lite (vx, vyaw mintavétel, 1.5 s szimuláció, költség = akadály + social + cél-eltérés + simaság). Tiszta függvény, `nav_local.py`, egységtesztelve.
- [ ] **NAV-3** Ember előtt a jobb oldalon kerül (konfigurálható), nem vág át az ember előtt, ha az a robot irányába mozog.
- [ ] **NAV-4** Elakadás: 10 s haladás nélkül → újratervezés; 3 sikertelen → `blocked` + `mc.core.anomaly`.

---

## 7. OmniView UI (digital-twin bővítés) — a „játék” élmény

Technológia: vanilla JS + three.js (cdnjs-ről, már használt), **nincs build-lépés, nincs React** (CLAUDE.md).

### 7.1 Jelenet
- [ ] **UI-1** Új oldal: `digital-twin/static/omni.html` + `omni.js` (a meglévő `index.html` mellett, közös modulokkal).
- [ ] **UI-2** Kutya 3D modell: a `go2_description.urdf` + `.dae` mesh-ek betöltése (three.js `ColladaLoader` + saját minimál URDF-parser vagy `urdf-loader` cdn-ről). A mesh-ek átmásolása a `web_dashboard/static/go2_description/`-ból (vagy közös statikus útvonal).
- [ ] **UI-3** Élő ízületi szögek (`LowState` 12 motor) WebSocketen 20 Hz → a lábak valóban úgy mozognak, mint a roboton. Adat hiányában idle-animáció.
- [ ] **UI-4** **Bowl / surround view:** a robot köré egy tál alakú mesh (sík padló r < 3 m, felette parabolikus fal r = 3–15 m); a fragment shader a 4 kameratextúrát vetíti rá a kalibráció (K, D, `T_base_cam`) alapján, halszem-modellel, a GPU-n. Az átfedésben súlyozott keverés (feathering), expozíció-kiegyenlítés kameránkénti gain-uniformmal. **Ez a 360°-os varrás, teljes egészében a böngészőben.**
- [ ] **UI-5** A bowl alakja adaptív (2. fázis): a padló-sík a LiDAR-talajmagasságból, a tál sugara a legközelebbi akadályok távolságából (így kevésbé torzulnak a közeli tárgyak).
- [ ] **UI-6** Nézetmódok (gyorsbillentyűvel):
  1. **Orbit** (3. személyű, kutya középen, szabad forgatás) — alapértelmezett
  2. **Chase** (a kutya mögött, a mozgást követi)
  3. **Top-down** (2D térkép + emberek + útvonal)
  4. **FPV** (a kamera szemszögéből, a kiválasztott irányba)
  5. **Point-cloud** (csak a színes voxeltérkép, a kamerakép nélkül)
- [ ] **UI-7** RGB-térpontfelhő: `THREE.Points` csempénként, `BufferGeometry` delta-frissítéssel (`OM-20`), pontméret távolság szerint, LOD (távoli csempék ritkítva). Cél: 2 M pont 60 fps-en egy laptop-GPU-n.
- [ ] **UI-8** Élő LiDAR-scan rétegként (külön szín / magasság-színezés), kapcsolható.
- [ ] **UI-9** 2D grid a padlón (a meglévő digital-twin floor/walls renderje), átlátszósággal.

### 7.2 Emberek és HUD
- [ ] **UI-10** Emberek: hologram-szerű kapszula / sziluett a 3D-pozícióban, `gid` címke, távolság, sebességvektor-nyíl, a predikált 2 s-os pálya szaggatott vonallal. Színe zóna szerint (zöld / sárga / narancs / piros).
- [ ] **UI-11** Biztonsági zónák körgyűrűként a kutya körül a padlón (`mc.safety.state`), pulzál, ha SLOW/STOP.
- [ ] **UI-12** HUD (futurisztikus, de olvasható): akku, sebesség, `safety` szint, fps kameránként, GPU%/hő, felfedezett terület m²-ben, aktív mód, kapcsolat-minőség. Radar-minimap a sarokban (360° emberek + akadályok).
- [ ] **UI-13** Kattintás a padlóra → `goto` (meglévő `/api/goto`); jobb klikk → „ide ne menj” (no-go zóna, a `mapping` kapja meg).
- [ ] **UI-14** Felfedezés-panel: Start/Stop explore, return home, patrol, felfedezési határ (geofence) rajzolása.
- [ ] **UI-15** Kalibráció-overlay kapcsoló (`CAL-6`), kamera-egészség panel.
- [ ] **UI-16** Felvétel / visszajátszás: a session (pose, persons, voxel-delták, alacsony felbontású videó) a `blackbox`-ba, és a UI-ban idővonal-csúszkával visszanézhető.
- [ ] **UI-17** Teljesítmény-mód a UI-ban (laptop / tablet / telefon): felbontás, pontszám, shader-minőség.
- [ ] **UI-18** Látvány: bloom (`UnrealBloomPass`, kapcsolható), sci-fi rács-padló, scan-hullám effekt az új LiDAR-pontokon. Mind kikapcsolható; a funkció elsőbbséget élvez a látvány előtt.

---

## 8. Jövőbeli bővítések (előkészítés most)

### 8.1 Hő- és IR-látás (éjszakai mód)
- [ ] **FUT-1** A kamera-adatmodellben `modality` mező (`rgb|thermal|nir`) már az 1. verzióban (`cameras.yaml`, `mc.omni.persons`).
- [ ] **FUT-2** Hőkamera-kalibráció: fűtött / hűtött mintás tábla (pl. alumínium tábla lyukakkal), ugyanaz a `CAL-*` lánc.
- [ ] **FUT-3** Ember-detektálás hőképen: külön, kicsi TRT-modell (pl. FLIR ADAS-adatsoron finomhangolt YOLO-n), vagy egyszerű hő-blob + LiDAR-klaszter fúzió.
- [ ] **FUT-4** Voxeltérkép új csatorna: `temp` (°C), a UI-ban színskála-váltóval (RGB / hő / fúzió).
- [ ] **FUT-5** Automatikus mód-váltás fényerő alapján: nappal RGB, alkonyatkor RGB + IR-lámpa, sötétben NIR + hő. A `safety_guard` sötétben szigorúbb zónákkal dolgozik (`SAF-6` erősebben).

### 8.2 Irányított mikrofon / mikrofontömb
- [ ] **FUT-6** DOA (hangirány): GCC-PHAT / SRP-PHAT a mikrofontömbön, CPU-n, 10 Hz. Kimenet: `mc.audio.doa` (`azimut`, `elevation`, `energy`, `class`).
- [ ] **FUT-7** Hangosztályozás (beszéd, kiáltás, csattanás, kutyaugatás) kis CNN-nel (pl. YAMNet-tflite osztály).
- [ ] **FUT-8** Fúzió: a DOA-irányba eső person-track → „beszélő ember” jelölés; ha nincs track → hangforrás-marker a 3D-térképen (a sugarat a LiDAR adja).
- [ ] **FUT-9** Pan-servo: a DOA-ra fordul, beamforming-gal együtt; a meglévő `audio` pillérbe (9107) integrálva.
- [ ] **FUT-10** Az UI-ban a hangforrások hullám-ikonként jelennek meg a 3D-ben, irány + erősség.

---

## 9. Erőforrás-büdzsé (Jetson Orin NX)

Célok MAXN módban, a meglévő `perception`-nel együtt futva. Mindegyik **mérendő** (`tegrastats`), a számok tervértékek.

| Modul | Hz | GPU | CPU | HW-blokk |
|---|---|---|---|---|
| Rögzítés 4× (dekód) | 20 | ~0 | < 5% | NVJPG / ISP |
| Rektifikálás 4× | 10 | < 3 ms | ~0 | VIC / VPI |
| YOLO INT8 batch=4 | 10 | ≤ 25 ms | < 10% | TensorRT |
| Tracking + fúzió | 10 | — | < 5% | — |
| LiDAR-színezés + voxel | 5 | ≤ 8 ms | < 10% | CUDA |
| Stream (JPEG vagy H.264) | 10 | ~0 | < 5% | NVJPG / NVENC |
| KISS-ICP odometria | 10 | — | 1–2 mag | — |
| `perception` (meglévő, elöl) | 15 | ~19 ms | 26% | TensorRT |
| **Összesen (cél)** | | **< 70% GPU** | **< 60% CPU** | hőmérséklet < 80 °C |

- [ ] **BUD-1** `budget.py`: 3 szint (`full`, `eco`, `survival`). Váltás GPU-hő > 80 °C, GPU > 85% vagy dropped frame-ek esetén. `eco`: YOLO 5 Hz, színezés 2 Hz. `survival`: csak a menetirányú kamera + LiDAR-safety. A safety soha nem kerül le.
- [ ] **BUD-2** `perception` és `omni` GPU-megosztás: közös TRT-engine-cache, a CUDA-streamek prioritása (a safety-releváns detektálás magasabb).
- [ ] **BUD-3** Memóriabüdzsé: az `omni` konténer ≤ 3 GB, voxel-hash fix kapacitással, nincs korlátlan lista.
- [ ] **BUD-4** Benchmark-szkript (`omni/bench.py`): MockSource-ból teljes pipeline, kimenet: modulonkénti p50/p95 latencia, fps, GPU%. CI-ben a mock-mód fut, Jetsonon a valódi.

---

## 10. Ütemezés / fázisok

Minden fázis végén: egységtesztek zöldek (`python -m pytest tests -q`), README frissítve, `STATUS.md` frissítve, mérési eredmények a `docs/`-ban.

| Fázis | Tartalom | Feladat-ID-k | Elfogadás |
|---|---|---|---|
| **F0 Előkészítés** | hardverválasztás, branch-ek, config-séma, MockSource, port-foglalás | HW-1..2, OM-1..3, CAL-5 | mock 4 kamera + XT16 visszajátszva, `GET /health` él |
| **F1 Kalibráció + nyers 360 UI** | kamerák felszerelve, intrinzika, extrinzika, bowl-nézet, kutya 3D | HW-3..6, CAL-1..6, OM-4..6, OM-24, UI-1..4, UI-6 | a böngészőben varratmentes 360 bowl, kutya középen, 10 fps |
| **F2 Ember 360** | rektifikálás, YOLO batch, track, LiDAR-mélység, fúzió, UI-emberek | OM-7..15, UI-10, UI-12 | OM-15 teljesül, büdzsén belül |
| **F3 Safety (P0)** | `safety_guard`, zónák, predikció, bekötés, tesztprotokoll | SAF-1..10 | minden mozgás a guardon át; fizikai teszt-protokoll lefutott |
| **F4 RGB-térpont** | deskew, színezés, voxel, delta-stream, export | OM-16..23, UI-7..8, MAP-3 | OM-23 teljesül, a UI-ban élő színes felhő |
| **F5 Autonóm felfedezés** | LiDAR-odometria, social layer, frontier, lokális tervező, módok | MAP-1..7, NAV-1..4, UI-13..14 | 100 m² iroda bejárva emberek között, 0 safety-sértés |
| **F6 Csiszolás** | WebRTC, adaptív bowl, visszajátszás, látvány, büdzsé-szabályzó | OM-25..26, UI-5, UI-15..18, BUD-1..4, CAL-7..8, MAP-2 | 1 órás futás, < 80 °C, nincs memóriaszivárgás |
| **F7 Éjszaka** | hő + NIR | FUT-1..5 | ember-detektálás sötétben ≥ 90% recall 6 m-en |
| **F8 Hallás** | mikrofontömb, DOA, pan-servo | FUT-6..10 | beszélő irány ±15°-on belül, a 3D-ben megjelenik |

Párhuzamosítható (multi-agent): F1 UI ↔ F2 detektálás ↔ F3 safety-logika (tiszta függvények), mind MockSource-on.

---

## 11. Kockázatok

| Kockázat | Hatás | Kezelés |
|---|---|---|
| USB-sávszél / kiesés 4 kamerával | képkocka-vesztés | GMSL / CSI előnyben; USB-n 2 vezérlő, MJPEG |
| Pontatlan kamera–LiDAR kalibráció | rossz színezés, rossz ember-távolság | CAL-3 célpont + célpont nélküli finomítás, CAL-7 drift-figyelés |
| Rolling shutter + forgás | elmosott színezés | global shutter / alacsony expozíció, deskew, forgás közben a színezés súlya csökken |
| GPU-túlterhelés (perception + omni) | latencia, hő | BUD-1 adaptív szintek; a safety mindig prioritás |
| Halszem-szélen gyenge YOLO | ember-kihagyás | hengeres rektifikálás, átfedés, LiDAR-klaszter tartalék (SAF-6) |
| Böngésző-teljesítmény (gyenge kliens) | akadozó UI | UI-17 teljesítmény-mód, LOD |
| JetPack 5 / Python 3.8 korlátok | lib-inkompatibilitás | a `perception` bevált base image-e, verziók pin-elve |
| Safety-hiba autonóm módban | sérülés | független `safety_guard`, fail-safe, fizikai protokoll, review kötelező |

---

## 12. Nyitott kérdések (döntés kell)

1. Kamera-interfész: GMSL2-kit vs. USB? (költség vs. megbízhatóság)
2. Pontos Jetson-modell / RAM (Orin NX 8 vagy 16 GB)? A büdzsé ettől függ.
3. A `perception` (RealSense, elöl) megmarad párhuzamosan, vagy az `omni` kiváltja az első kamerát?
4. A UI fő kliense laptop, tablet vagy telefon? (shader-minőség)
5. Beltéri vagy kültéri elsődleges használat? (expozíció, IR, GPS)
