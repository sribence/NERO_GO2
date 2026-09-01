# webrtc_bridge

Kamera + LiDAR + telemetria hozzáférés a Go2-höz a **hivatalos** Unitree WebRTC protokollon keresztül ([unitree_webrtc_connect](https://github.com/legion1581/unitree_webrtc_connect), MIT) — ugyanaz, amit a mobilapp is használ, nem kell jailbreak.

**Ez a kód nagyrészt egy helyi LLM-mel (`qwen2.5-coder:14b`) generáltatva készült, kézi átnézéssel/javítással** — ld. [docs/13-lokalis-llm-delegalas.md](../../docs/13-lokalis-llm-delegalas.md) a workflow-ért.

## Státusz (2026-09-01): ÉLŐ ROBOTTAL TESZTELVE — kamera+telemetria működik, LiDAR pontfelhő még nem

A build sikeresen felépült Jetsonon, a konténer `network_mode: host`-on **hibátlanul** csatlakozik a robothoz (nem érinti a `rosbridge`-nél talált SIGSEGV-hibát, mert ez tiszta Python/`aiortc`, nem ROS2/DDS-alapú).

Élő teszt közben 3 valós API-hibát találtunk és javítottunk (a korábbi, sosem tesztelt LLM-generált kód "legjobb tipp" feltételezéseiben):

1. **`conn.video` nem async-iterálható** — a `WebRTCVideoChannel` egy callback-regisztrációs API (`add_track_callback`), nem generátor.
2. **`conn.data_channel_pubsub` nem létezik** — a helyes útvonal `conn.datachannel.pub_sub`, és a `subscribe(topic, callback)` szinkron hívás, nem async generátor.
3. **A videó és a LiDAR explicit "bekapcsolást" igényel** a data channelen keresztül, mielőtt bármi adat jönne (`conn.video.switchVideoChannel(True)`, illetve LiDAR-hoz `disableTrafficSaving(True)` + `rt/utlidar/switch: "on"` publikálás) — ez egyik könyvtár-README-ben sincs explicit dokumentálva, csak a hivatalos `examples/` mappában derült ki.

### Ami működik
- `/health`, `/state` — élő IMU/motor/akkumulátor-adat (pl. 46% SoC, 28.8V, motor-hőmérsékletek)
- `/camera.jpg` — élő kameraframe (JPEG, ~65-70KB), valós robot-kép

### Ami (még) nem működik: `/lidar`
A LiDAR **fizikailag forog és adatot termel** (`rt/utlidar/lidar_state` topicon élő `cloud_frequency`/`cloud_size`/`com_rotation_speed` adat érkezik folyamatosan), DE a `rt/utlidar/voxel_map_compressed` topic — amiről a tényleges pontfelhőt várnánk — **soha nem küld üzenetet**, annak ellenére, hogy a kódunk **szóról szóra megegyezik** a könyvtár hivatalos `examples/go2/data_channel/lidar/lidar_stream.py` példájával (ellenőrizve `gh api` segítségével, nyers forrásból).

**Legvalószínűbb ok:** a "voxel map" egy magasabb szintű, feldolgozott (SLAM/mapping-szerű) termék, nem a nyers szenzor-adat — feltehetően csak akkor publikálódik, ha a robot egy adott üzemmódban van, NEM pedig a jelenlegi állapotában (a robot most a hivatalos állványán, **damping módban** áll — ld. [docs/10-munkamenet-naplo-2026-08-31.md](../../docs/10-munkamenet-naplo-2026-08-31.md)). Ezt csak úgy lehet megerősíteni/cáfolni, hogy a robotot normál (nem damping) állapotban teszteljük újra.

**Nyitott TODO:**
- [ ] Újratesztelni `/lidar`-t, amíg a robot NEM damping módban, NEM az állványon van
- [ ] Ha továbbra sem jön adat: megnézni, kell-e egy "mapping mód" bekapcsoló API-hívás (pl. a `SLAM_QT_COMMAND`/`rt/qt_command` topicon) a voxel-map generáláshoz

## Endpointok

| Endpoint | Mit ad |
|---|---|
| `GET /health` | `{"status": "ok", "connected": bool}` |
| `GET /camera.jpg` | legutóbbi kameraframe JPEG-ként, 404 amíg nincs |
| `GET /lidar` | legutóbbi LiDAR pontfelhő JSON-ban (max 5000 pontra ritkítva) — **jelenleg mindig 404, ld. fent** |
| `GET /lidar_state` | LiDAR szenzor-státusz (forgási sebesség, felhő-frekvencia, hibaállapot) — ez MŰKÖDIK |
| `GET /state` | legutóbbi lowstate + sportmodestate + távirányító adat |

## Firmware-verzió függő beállítás

Ezen a robotomon (SN `B42D4000Q7OANL8A`) **kell** az AES-128 kulcs (firmware ≥ 1.1.15). Lekérve: `unitree-fetch-aes-key` CLI-vel (Unitree fiók login szükséges hozzá, **NEM commitolható a publikus repóba** — csak futásidejű env-változóként add át: `UNITREE_AES_128_KEY`).

## Egyszerre csak egy kliens

A robot csak **egy WebRTC-kliens** kapcsolatot enged egyszerre — ha közben a hivatalos mobilapp is csatlakozva van, ez a bridge `RobotBusyError`-t fog kapni. Ha egy kapcsolat "megszakad" (pl. a klienst hirtelen leállítjuk anélkül, hogy `disconnect()`-elne), a robot oldalán néhány másodpercig "foglaltnak" tűnhet a slot (`DataChannelTimeoutError`) — várj 10-20 másodpercet és próbáld újra.
