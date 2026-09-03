# Taszklista — sorrendben, fázisonként

Ez a konkrét, végrehajtható feladatlista a [11-oktatocsomag-terv.md](11-oktatocsomag-terv.md) architektúrájához. Minden taszknál jelölve, hogy kell-e hozzá fizikai robot-kapcsolat.

Jelmagyarázat: 🤖 = kell hozzá élő robot · 💻 = robot nélkül, laptopon csinálható

## Fázis 0 — alapok (KÉSZ, 2026-08-31)

- [x] 💻 Hálózat/rendszer/ROS/DDS teljes feltérképezés
- [x] 💻 NERO_GO2 repó + biztonsági szabályzat
- [x] 🤖 Ideiglenes internet a robotnak
- [x] 🤖 ROS2 Foxy Jetson dev image-ek lehúzva + helyi mentés
- [x] 💻 `foxglove_bridge` Dockerfile + GPG-hiba javítás (build nincs végigfuttatva)
- [x] 💻 `mock_robot` — robot nélküli fejlesztői stack (`docker/mock_robot/`), 2026-09-03, élőben tesztelve böngészőben
- [x] 💻 `/showcase` 3D digitális iker — élő, animált robotváz + HUD-telemetria, mock-adaton tesztelve, ld. [14-capability-showcase-projekt.md](14-capability-showcase-projekt.md)
- [ ] 🤖 `/showcase` élő tesztelése valós robot-DDS-adattal (a `_init_sdk` ág már fel van készítve motor_q/tau/temp adatra)

## Fázis 1 — érzékelés/kommunikáció alapréteg

- [x] 🤖 `rosbridge` (a `foxglove_bridge` helyett) build befejezve — 2026-09-01, ld. [docker/rosbridge/README.md](../docker/rosbridge/README.md)
- [ ] 🤖 **BLOKKOLVA:** élő kapcsolat tesztelése — `network_mode: host`-on minden ROS2/rclpy-folyamat SIGSEGV-be fut valódi `eth10` NIC-en (bridge hálózaton viszont nem éri el a robot DDS-multicast forgalmát) — ld. részletek [docker/rosbridge/README.md](../docker/rosbridge/README.md) "KRITIKUS, MEGOLDATLAN HIBA" szakasz
- [ ] 🤖 A [09-dds-interfesz-eltapasztalas.md](09-dds-interfesz-eltapasztalas.md) `eth0`/`eth10` hiba hatásának ellenőrzése — látszanak-e a `rt/...` topicok (a fenti SIGSEGV-hiba miatt még nem tesztelhető)
- [x] 💻 `unitree_webrtc_connect` (MIT) áttekintése, licenc-ellenőrzés, fork/vendor-elés a `docker/webrtc_bridge/` alá — 2026-08-31, helyi LLM-mel generálva+javítva, ld. [13-lokalis-llm-delegalas.md](13-lokalis-llm-delegalas.md)
- [x] 🤖 `webrtc_bridge` Docker-konténer élő tesztelése — 2026-09-01, kamera+telemetria MŰKÖDIK, 3 API-hiba javítva (ld. [docker/webrtc_bridge/README.md](../docker/webrtc_bridge/README.md))
- [ ] 🤖 LiDAR pontfelhő (`/lidar`) — a szenzor forog és adatot termel, de a `voxel_map_compressed` topic nem küld semmit; gyanú: damping mód/állvány blokkolja — újratesztelendő normál állapotban
- [ ] 🤖 Intel RealSense D435i fizikai csatlakozásának azonosítása (Jetson USB vs. mozgásvezérlő) + `librealsense`/`realsense-ros` Docker-konténerben tesztelve
- [ ] 💻 Ezen a ponton dokumentálni: melyik szenzor melyik csatornán, milyen formátumban érhető el (referencia-táblázat a repóba)

## Fázis 2 — webes irányítópult

- [x] 💻 `go2_dashboard` (Flask) áttekintése, licenc-ellenőrzés, fork a `docker/web_dashboard/` alá — 2026-08-31, helyi LLM vázlat + jelentős kézi átírás (ld. [13-lokalis-llm-delegalas.md](13-lokalis-llm-delegalas.md))
- [x] 💻 NERO_GO2 saját dizájn/branding a felületre (diákbarát, látványos) — sötét téma, magyar UI szöveg, arm/disarm biztonsági kapcsoló
- [x] 🤖 `unitree_sdk2py` függőség megoldva — 2026-09-01, hivatalos `unitreerobotics/unitree_sdk2_python` + natúr CycloneDDS-build újrahasznosítva (ld. `docker/web_dashboard/README.md`)
- [x] 🤖 DDS-kapcsolat + telemetria élő tesztelve — 2026-09-01, MŰKÖDIK ("DDS/SportClient ready", élő voltage/current/temp adat)
- [ ] 🤖 Mód-váltó gombok/joystick élő tesztelése (állj/ülj/damping — **óvatosan, ld. biztonsági szabályok**)
- [ ] 🤖 LiDAR 3D-nézet beágyazása a webes felületbe (Foxglove-elvek átvéve, vagy három.js-alapú saját megjelenítő)
- [ ] 🤖 RealSense mélységkép-panel hozzáadása
- [ ] 💻 Docker Compose-ba szervezve az összes eddigi konténer (dev, foxglove_bridge, webrtc_bridge, web_dashboard) egy stack-ként

## Fázis 3 — navigáció / waypoint-feladatok

- [ ] 💻 `autonomy_stack_go2` (Point-LIO + FAR Planner) áttekintése, függőségek listázása
- [ ] 🤖 Docker-konténerbe integrálva, IMU-kalibráció elvégezve (a projekt ezt előfeltételként írja)
- [ ] 🤖 Alap SLAM-térképezés tesztelése (a meglévő `graph_pid_ws` LiDAR-driverekkel is összevetve, ld. [05-egyedi-slam-stack.md](05-egyedi-slam-stack.md))
- [ ] 🤖 Egyetlen cél-pont navigáció tesztelése (RViz-ből vagy a saját webes felületről)
- [ ] 💻 "Felvevő pont / letevő pont" workflow megtervezése a webes felületen (két pont kijelölése térképen, `/follow_waypoints` action meghívása)
- [ ] 🤖 Teljes "menj a pontra, csinálj valamit, menj a másik pontra" demo-szekvencia tesztelése

## Fázis 4 — objektumkövetés / AI

- [ ] 💻 `unitree-go2-follow-system` (YOLOv8+PID) áttekintése
- [ ] 🤖 YOLO modell tesztelése a RealSense/kamera streamen (felismerési pontosság, Jetson terhelés/hő ellenőrzése `tegrastats`-tal)
- [ ] 🤖 Objektum-kijelölés a webes felületről (kattints a kamera-képen egy dobozra → kövesse azt)
- [ ] 🤖 Követés + mozgásvezérlés összekötése (a `rt/sportmodecmd` felé), **fokozott óvatossággal, fizikai biztonsági távolság betartásával**

## Fázis 5 — oktatási csomagolás

- [ ] 💻 Bemutató forgatókönyv/script diákoknak (mit mutatunk, milyen sorrendben, mekkora biztonsági terület kell)
- [ ] 💻 Rövid, vizuális dokumentáció/cheat sheet a repóba (mi micsoda, hogyan indítjuk el élőben)
- [ ] 💻 Hibaelhárítási útmutató (mi a teendő, ha X nem működik demó közben)

## Megjegyzés a sorrendhez

A fázisok **egymásra épülnek** (1 → 2 → 3 → 4), de a 💻-jelölt taszkok bármikor előre vehetők, amikor nincs robot-hozzáférés — ahogy ma este is történt. Javaslom, hogy minden robotos munkanap elején nézzük át, melyik 🤖-taszk van soron, és azt köztük végezzük el elsőként, amíg friss/jó az internet és a robot ideje.
