# Foxglove Studio — NERO_GO2 alapértelmezett layout

`nero_go2_default.layout.json` — importálható a Foxglove Studio-ba (Layout → Import from file). **Robot nélkül, előre elkészítve** — élő adattal még nem lett tesztelve, holnap a robot bekapcsolása után finomhangoljuk.

## Panelek

| Panel | Topic | Mit mutat |
|---|---|---|
| 3D | `/utlidar/cloud_deskewed` | beépített LiDAR torzításmentesített pontfelhője, `z` szerint színezve |
| Raw Messages | `/lf/lowstate` | alacsony szintű állapot 20Hz-en: akkumulátor, láberő, ventilátor-fordulatszám |
| Raw Messages | `/lf/sportmodestate` | mozgásállapot 20Hz-en: pozíció, sebesség, testtartás |
| Raw Messages | `/wirelesscontroller` | távirányító nyers adatai |

## Miért Raw Messages és nem Plot

A pontos mezőnevek (`battery.voltage`, `foot_force[0]` stb.) a `unitree_dds_idl` JSON-sémáiból derülnek ki pontosan — ezt csak élő kapcsolattal, a tényleges üzenetstruktúrát látva tudjuk véglegesíteni Plot-panelekre (grafikonokhoz konkrét mezőútvonal kell). Most szándékosan Raw Messages panelekkel indulunk, amik bármilyen struktúrát mutatnak kiegészítés nélkül — holnap, élő adaton, ezekből építünk konkrét Plot-panelt (pl. akkumulátor-feszültség grafikon).

## Ismert limitáció: nincs kamera-panel

A `/frontvideostream` (elülső kamera) **WebRTC-n megy**, nem szabvány ROS2/DDS topicon (`rt/frontvideostream` "nem támogatott" a natív JSON-API-ban is, kifejezetten "webrtc-ből kell lekérni" megjegyzéssel a topic-katalógusban). A Foxglove natív Image panelje ezt **nem tudja közvetlenül megjeleníteni** — ehhez egy külön hidat kellene írni, ami a WebRTC videostreamet újra-publikálja `sensor_msgs/Image` vagy `foxglove_msgs/CompressedVideo` topicként. Ez egy külön TODO, nem a mostani layout része.

## Feltétel a működéshez

Ehhez a layouthoz **kell** a `foxglove_bridge` (ld. [../docker/foxglove_bridge/](../docker/foxglove_bridge/)), ami hidat képez a robot natív CycloneDDS/ROS2 rétege és a Foxglove Studio websocket-kapcsolata között. Ennek build-je jelenleg **folyamatban/nem véglegesített** — ld. a build-lognál talált GPG-kulcs hibát és annak javítását a Dockerfile-ban.

## TODO holnapra (robot bekapcsolása után)

- [ ] `foxglove_bridge` build befejezése és ellenőrzése (a GPG-kulcs javítás után újra kell futtatni, a kapcsolat menet közben megszakadt)
- [ ] `docker compose run` a bridge-re, `network_mode: host` szükséges a DDS discovery-hez (ld. [../docker/dev/README.md](../docker/dev/README.md) indoklás)
- [ ] Foxglove Studio-ból csatlakozás `ws://192.168.123.18:8765` (a `foxglove_bridge` alapértelmezett websocket portja)
- [ ] Ellenőrizni, hogy a `/utlidar/cloud_deskewed` topic tényleg látszik-e (a [09-dds-interfesz-eltapasztalas.md](../docs/09-dds-interfesz-eltapasztalas.md) `eth0` vs `eth10` hiba miatt lehet, hogy nem)
- [ ] A `lowstate`/`sportmodestate` JSON-séma alapján konkrét Plot-panelek hozzáadása (akkumulátor-feszültség, láberő grafikon)
