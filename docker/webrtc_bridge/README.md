# webrtc_bridge

Kamera + LiDAR + telemetria hozzáférés a Go2-höz a **hivatalos** Unitree WebRTC protokollon keresztül ([unitree_webrtc_connect](https://github.com/legion1581/unitree_webrtc_connect), MIT) — ugyanaz, amit a mobilapp is használ, nem kell jailbreak.

**Ez a kód nagyrészt egy helyi LLM-mel (`qwen2.5-coder:14b`) generáltatva készült, kézi átnézéssel/javítással** — ld. [docs/13-lokalis-llm-delegalas.md](../../docs/13-lokalis-llm-delegalas.md) a workflow-ért.

## Státusz (2026-09-04): ÉLŐ ROBOTTAL TESZTELVE — kamera+telemetria+LiDAR MIND működik

A build sikeresen felépült Jetsonon, a konténer `network_mode: host`-on **hibátlanul** csatlakozik a robothoz (nem érinti a `rosbridge`-nél talált SIGSEGV-hibát, mert ez tiszta Python/`aiortc`, nem ROS2/DDS-alapú).

Élő teszt közben 3 valós API-hibát találtunk és javítottunk (a korábbi, sosem tesztelt LLM-generált kód "legjobb tipp" feltételezéseiben):

1. **`conn.video` nem async-iterálható** — a `WebRTCVideoChannel` egy callback-regisztrációs API (`add_track_callback`), nem generátor.
2. **`conn.data_channel_pubsub` nem létezik** — a helyes útvonal `conn.datachannel.pub_sub`, és a `subscribe(topic, callback)` szinkron hívás, nem async generátor.
3. **A videó és a LiDAR explicit "bekapcsolást" igényel** a data channelen keresztül, mielőtt bármi adat jönne (`conn.video.switchVideoChannel(True)`, illetve LiDAR-hoz `disableTrafficSaving(True)` + `rt/utlidar/switch: "on"` publikálás) — ez egyik könyvtár-README-ben sincs explicit dokumentálva, csak a hivatalos `examples/` mappában derült ki.

### Ami működik
- `/health`, `/state` — élő IMU/motor/akkumulátor-adat (pl. 46% SoC, 28.8V, motor-hőmérsékletek)
- `/camera.jpg` — élő kameraframe (JPEG, ~65-90KB), valós robot-kép
- `/lidar` — élő pontfelhő (max 5000 pontra ritkítva), **2026-09-04 óta megoldva**

### `/lidar` dekódolás — 2026-09-04, élő robottal megfejtve
A `rt/utlidar/voxel_map_compressed` topic korábban azért tűnt "nem működőnek", mert a raktári "libvoxel" dekóder (`unitree_webrtc_connect`, `lidar/lidar_decoder_libvoxel.py`) **nem sima pontlistát ad vissza**, hanem egy voxel-mesh puffer-készletet (`{"positions": <numpy uint8 tömb>, "uvs", "indices", "point_count", "face_count"}`) — ráadásul ez a decoder-kimenet a datachannel-üzenet **belső** `data` mezőjében van, nem a külsőben. Sem a könyvtár, sem a hivatalos `examples/go2/data_channel/lidar/plot_lidar_stream.py` nem dokumentálja pontosan ezt a formátumot.

A `positions` mező tartalma egy ideiglenes `/lidar_debug` végponttal (hex/int16/uint16/float32/int32 értelmezések egymás mellett) derült ki élő robot-adaton: **fixpontos int16 rács-index, 256-os (2⁸) skálázással**:
```
valós_rács_index = raw_int16 / 256.0
világkoordináta   = origin + valós_rács_index * resolution
```
(`origin` és `resolution` a datachannel-üzenet külső `data` mezőjéből jön, pl. `resolution=0.05`, `origin=[-3.225,-3.225,-0.575]`, `width=[128,128,38]` — egy 6.4×6.4×1.9m-es, 5cm-es voxel-rács.)

Élő teszt: 5000 pont, fizikailag értelmes koordináták (~1.8m/-1.4m/-0.2m tartományban, a robot közelében lévő felületeket írja le).

## Endpointok

| Endpoint | Mit ad |
|---|---|
| `GET /health` | `{"status": "ok", "connected": bool}` |
| `GET /camera.jpg` | legutóbbi kameraframe JPEG-ként, 404 amíg nincs |
| `GET /lidar` | legutóbbi LiDAR pontfelhő JSON-ban, `[[x,y,z],...]` (max 5000 pontra ritkítva) — **működik** |
| `GET /lidar_state` | LiDAR szenzor-státusz (forgási sebesség, felhő-frekvencia, hibaállapot) — ez MŰKÖDIK |
| `GET /state` | legutóbbi lowstate + sportmodestate + távirányító adat |

## Firmware-verzió függő beállítás

Ezen a robotomon (SN `B42D4000Q7OANL8A`) **kell** az AES-128 kulcs (firmware ≥ 1.1.15). Lekérve: `unitree-fetch-aes-key` CLI-vel (Unitree fiók login szükséges hozzá, **NEM commitolható a publikus repóba** — csak futásidejű env-változóként add át: `UNITREE_AES_128_KEY`).

## Egyszerre csak egy kliens

A robot csak **egy WebRTC-kliens** kapcsolatot enged egyszerre — ha közben a hivatalos mobilapp is csatlakozva van, ez a bridge `RobotBusyError`-t fog kapni. Ha egy kapcsolat "megszakad" (pl. a klienst hirtelen leállítjuk anélkül, hogy `disconnect()`-elne), a robot oldalán néhány másodpercig "foglaltnak" tűnhet a slot (`DataChannelTimeoutError`) — várj 10-20 másodpercet és próbáld újra.
