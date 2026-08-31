# Oktatócsomag terv — "mit tud a robot" bemutatóprogram diákoknak

## Cél

Egy látványos, komplex demó-csomag, amivel diákoknak bemutatható: a robot mobilitása, érzékelői (LiDAR, RealSense D435i, kamera), és AI-képességei (objektumfelismerés/-követés, autonóm navigáció). Webes felületről irányítható, élő adatmegjelenítéssel.

## Megerősített hardver (EDU verzió)

- **Intel RealSense D435i** mélységkamera (3D+RGB), beépítve az EDU verzióba — ezt kereste a felhasználó "intellisense" néven
- Beépített LiDAR (`rt/utlidar/*` DDS-topicok, ld. [04-gyari-unitree-szoftver.md](04-gyari-unitree-szoftver.md))
- Az EDU csomaghoz tartozó **extra, erősebb LiDAR-modul** (a pontos típus a fizikai eszközön ellenőrizendő — Hesai/Livox driver már megvan a `graph_pid_ws`-ben, ld. [05-egyedi-slam-stack.md](05-egyedi-slam-stack.md))

## Architektúra — négy réteg, meglévő nyílt projektekre építve

```
┌─────────────────────────────────────────┐
│ 4. Objektumkövetés / AI                  │  unitree-go2-follow-system (YOLOv8+PID)
├─────────────────────────────────────────┤
│ 3. Navigáció (waypoint, "menj oda")      │  autonomy_stack_go2 (Point-LIO + FAR Planner)
├─────────────────────────────────────────┤
│ 2. Webes felület (irányítás, megjelenítés)│  go2_dashboard alapokra építve + Foxglove
├─────────────────────────────────────────┤
│ 1. Érzékelés / kommunikáció              │  unitree_webrtc_connect (kamera/LiDAR/telemetria)
└─────────────────────────────────────────┘
```

### 1. réteg — érzékelés/kommunikáció

**[unitree_webrtc_connect](https://github.com/legion1581/unitree_webrtc_connect)** (Python, MIT) — a hivatalos mobilapp-protokollt (WebRTC) használja, nem kell jailbreak/firmware-módosítás. Kamera-videó, LiDAR pontfelhő-dekódolás, IMU/motor/akku-telemetria egy Python könyvtárból.

### 2. réteg — webes felület

**[go2_dashboard](https://github.com/bentheperson1/go2_dashboard)** (Flask + web frontend) alapokra építve: élő kamera, virtuális joystick, mód-váltó gombok (állj/ülj/hullámozz/damping). Ezt bővítenénk RealSense mélységkép-panellel és LiDAR 3D-nézettel (a Foxglove-munkánkból átvéve, ld. [foxglove/](../foxglove/)).

### 3. réteg — navigáció

**[autonomy_stack_go2](https://github.com/jizhang-cmu/autonomy_stack_go2)** — Point-LIO SLAM + FAR Planner útvonaltervező, cél-pont RViz-ből, akadálykerüléssel. Ez adja a "kattints egy pontra a térképen, a robot odamegy" funkciót — ebből tudunk "felvevő pont / letevő pont" jellegű, robotporszívó-szerű feladatvégrehajtást építeni.

### 4. réteg — objektumkövetés/AI

**[unitree-go2-follow-system](https://github.com/orisharabi/unitree-go2-follow-system)** — YOLOv8 objektumdetektálás + PID-alapú követés. Ebből tudunk "jelöld ki az objektumot, a robot kövesse" demót építeni.

## Fejlesztési stratégia

- **Amit a robot nélkül, a laptopon el lehet kezdeni:** a fenti repók áttekintése, fork-olása, kód-adaptáció megtervezése, a webes felület UI-jának megtervezése/prototípusa
- **Amihez kell a robot:** minden éles teszt (kamera/LiDAR valós adat, navigáció, követés-teszt)
- **Docker-elv változatlan:** minden réteg a natív rendszertől szeparált Docker-konténerben fusson (ld. [00-BIZTONSAGI-SZABALYOK.md](00-BIZTONSAGI-SZABALYOK.md))

## Fázisterv (javaslat, sorrend egyeztetendő)

1. **Fázis 1 — alapok:** `foxglove_bridge` befejezése (folyamatban), `unitree_webrtc_connect` integrálása Docker-konténerbe, első élő kamera+LiDAR teszt
2. **Fázis 2 — webes irányítópult:** `go2_dashboard` fork, saját NERO_GO2 dizájnnal, mód-váltás + élő kamera/LiDAR/RealSense panelek
3. **Fázis 3 — navigáció:** `autonomy_stack_go2` integrálása, kattintásos cél-pont, "felvevő/letevő pont" feladat-demo
4. **Fázis 4 — objektumkövetés:** YOLO-alapú követés-demo, kijelölhető célponttal

## Nyitott kérdések

- A fizikai extra EDU LiDAR pontos típusa/csatlakoztatása — holnap, robotnál ellenőrizendő
- A RealSense D435i pontosan melyik boardhoz van kötve (Jetson USB vagy a mozgásvezérlőn keresztül?) — szintén helyszíni ellenőrzés kell
- Licencek: mindegyik talált projekt MIT vagy hasonló megengedő licenc, de ellenőrzendő fork előtt
