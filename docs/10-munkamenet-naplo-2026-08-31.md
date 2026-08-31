# Munkamenet-napló — 2026-08-31

## Amit ma csináltunk

1. **Feltérképezés** — teljes hálózati/rendszer/ROS/DDS/webes felület audit (ld. docs/01-09)
2. **NERO_GO2 repó létrehozva** — [github.com/sribence/NERO_GO2](https://github.com/sribence/NERO_GO2), publikus
3. **Ideiglenes internet a robotnak** — Windows ICS + registry-testreszabás (`192.168.123.0/24` scope), hogy a robot meglévő `.1`-es gateway-elvárása magától működjön. Részletek: [07-internet-megosztas.md](07-internet-megosztas.md)
4. **Docker tesztelve** — natívan működik ARM64 image-eken (`hello-world` OK)
5. **Két nagy ROS2 Jetson image lehúzva és lokálisan mentve:**
   - `dustynv/ros:foxy-desktop-l4t-r35.3.1` (13.2GB)
   - `dustynv/ros:foxy-ros-base-l4t-r35.3.1` (11.2GB)
   - Mentés helye a robotom: `~/nero_go2_backups/*.tar.gz` (`docker save` + gzip)
6. **`foxglove_bridge` build elkezdve forrásból** — ütközött egy ismert GPG-kulcs hibába, javítva a Dockerfile-ban, de **a build nem lett végigfuttatva** (a robot fizikailag kikapcsolásra került, mielőtt befejeződött volna)
7. **Foxglove Studio layout előkészítve** offline (robot nélkül) — [foxglove/nero_go2_default.layout.json](../foxglove/nero_go2_default.layout.json)

## Hálózati incidensek (tanulságok)

- **Telefon-tethering → WiFi váltás közben** a `docker pull` "megfagyott" — a TCP-kapcsolat élettelen maradt az ICS-forrás váltása után, a folyamat kill+restart-ra volt szükség. A kill véletlenül a már majdnem kész réteget is eldobta (2,8GB → 82MB visszaesés) — tanulság: ha ICS-forrást váltunk, számítsunk rá, hogy a folyamatban lévő letöltéseket újra kell indítani, és **ne öljük meg félbehagyva**, ha elkerülhető (inkább várjunk, hátha magától újrapróbálkozik).
- **A robot Ethernet-kábele menet közben kicsatlakozott** — a laptop "Ethernet" adaptere `Disconnected` állapotba került, ez azonnal, teljes kapcsolat-megszakadást okozott (nem csak lassulást). Erre figyelni kell fizikai fejlesztés közben — a kábelcsatlakozás rögzítettsége fontos hosszabb munkamenetekhez.

## Nyitott, holnapra váró feladatok

- [ ] `foxglove_bridge` build befejezése (a GPG-kulcs javítás után újra futtatni `docker compose build` a `docker/foxglove_bridge/` alatt)
- [ ] Foxglove Studio csatlakoztatása élőben, `ws://192.168.123.18:8765`
- [ ] A `foxglove/nero_go2_default.layout.json` finomhangolása élő adat alapján (pontos JSON-mezőnevek Plot-panelekhez)
- [ ] Ellenőrizni a [09-dds-interfesz-eltapasztalas.md](09-dds-interfesz-eltapasztalas.md)-ben leírt `eth0`/`eth10` DDS-hibát élesben — látszanak-e egyáltalán a `rt/...` topicok kívülről
- [ ] A `docker/dev/` fejlesztői konténer kipróbálása (eddig csak a nagy image lett lehúzva, maga a `docker compose build`/`run` még nem lett tesztelve)
- [ ] Mérlegelni: a `~/nero_go2_backups/` tartalmának lehozatala a robotról a laptopra/repóba is (jelenleg csak a robot saját diszkjén van, ami nem védi teljes hardver-meghibásodás ellen)
