# web_dashboard

A NERO_GO2 fő webes vezérlőpultja — élő kamera (a `webrtc_bridge`-ből proxyolva), telemetria, virtuális joystick, akció-gombok (állj fel, feküdj le, ülj, integess, szív).

Architektúra-minta ([go2_dashboard](https://github.com/bentheperson1/go2_dashboard) by bentheperson1, MIT) alapján, de **nem másolat** — friss implementáció, két külön szolgáltatásra bontva:

- **`webrtc_bridge`** (5001-es port) — kamera/LiDAR/health, a hivatalos WebRTC-protokollon
- **`web_dashboard`** (ez, 5002-es port) — webes UI + mozgásvezérlés, natív DDS-en (`unitree_sdk2py`) keresztül

**Miért két szolgáltatás:** a robot csak **egy** WebRTC-klienst enged egyszerre. Ha a `web_dashboard` is saját WebRTC-kapcsolatot nyitna (mint az eredeti go2_dashboard), az ütközne a `webrtc_bridge`-vel. A mozgásvezérlés natív CycloneDDS-en megy, ami teljesen külön csatorna — nem ütközik semmivel.

## ⚠️ Biztonsági "arm/disarm" mechanizmus

A mozgásvezérlés (joystick, akció-gombok) **alapból zárolva van** (`armed=False`). A felhasználónak explicit fel kell oldania ("Vezérlés zárolva" gombra kattintva), és **30 másodperc inaktivitás után automatikusan visszazáródik**. Ez szándékos — ld. [00-BIZTONSAGI-SZABALYOK.md](../../docs/00-BIZTONSAGI-SZABALYOK.md), a robot drága, véletlen mozgásparancs nem mehet ki felügyelet nélkül.

## Státusz (2026-09-01): ÉLŐBEN TESZTELVE — DDS-kapcsolat + telemetria MŰKÖDIK, mozgásparancsok még nincsenek élesben kipróbálva

### `unitree_sdk2py` függőség — megoldva
A hivatalos [unitreerobotics/unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python) csomagot használjuk (nem a legion1581 fork-ot). Ez pontosan **CycloneDDS 0.10.2**-t igényel forrásból fordítva — ehelyett a robot natúr rendszerén **már meglévő** buildet (`~/cyclonedds_ws/install/cyclonedds`) használjuk fel, bemásolva a Docker build contextbe (`cyclonedds_home/` — ez a mappa NEM kerül git-be, gépspecifikus build-előfeltétel, ld. `.gitignore`).

**Build előfeltétel** (a robotnál, minden tiszta klónozás után egyszer kell futtatni):
```bash
cp -r ~/cyclonedds_ws/install/cyclonedds docker/web_dashboard/cyclonedds_home
cp /usr/lib/aarch64-linux-gnu/libcrypto.so.1.1 /usr/lib/aarch64-linux-gnu/libssl.so.1.1 docker/web_dashboard/cyclonedds_home/lib/
```
Az utóbbi két fájl azért kell, mert a natúr `libddsc.so` régi OpenSSL 1.1-hez van linkelve, ami a modern Debian-alapú Python image-ből hiányzik.

### API-javítás
Az `_init_sdk()` korábbi verziója **kitalált API-kat** használt (`IDLDataClass`, `DDSChannelFactoryInitialize`, `create_standard_sdk`, `sdk.create_robot()`, `communicator.ChannelSubscriber`) — egyik sem létezik a valós csomagban. Javítva a hivatalos GitHub-repó forrása alapján (`gh api` a nyers kódért, mert a WebFetch/böngészős összegzés túl sokat veszít):
```python
from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_, SportModeState_
from unitree_sdk2py.go2.sport.sport_client import SportClient

ChannelFactoryInitialize(0, "eth10")
sub = ChannelSubscriber("rt/lowstate", LowState_)
sub.Init(handler, 10)
```
Az akció-metódusok (`Hello`, `Heart`, `Sit`, `RecoveryStand`, `StandDown`, `Move`) és a mezőnevek (`power_v`, `power_a`, `temperature_ntc1/2`, `velocity[0..2]`, `yaw_speed`) mind ellenőrizve lettek a hivatalos `SportClient`/IDL forrás ellen — mind helyesnek bizonyultak.

### Fontos: EZ NEM ütközik a `rosbridge` SIGSEGV-hibájával
A `rosbridge` (ROS2/`rclpy`/`rmw_cyclonedds_cpp`) `network_mode: host`-on valódi NIC-en összeomlott (ld. [docker/rosbridge/README.md](../rosbridge/README.md)). Ez a `unitree_sdk2py` viszont **raw CycloneDDS Python binding**, nem megy át a ROS2 `rclpy`/`rmw` rétegen — élőben tesztelve, **nem omlik össze**, ugyanazon `network_mode: host` + `eth10` NIC mellett.

### Élő teszt eredménye
```
INFO DDS/SportClient ready
data: {"voltage": 27.71, "current": 0.65, "avg_temp": 46.5, "velocity_x": 0.0, ..., "sdk_ready": true, "bridge_connected": true}
```
`/`, `/data` (SSE telemetria), `/camera_feed` (webrtc_bridge proxy) mind működnek.

## TODO

- [ ] Arm/disarm + joystick + akció-gombok élő tesztelése — **óvatosan, biztonsági távolságból, felügyelet mellett**
- [ ] `docker-compose.yml` frissítése a `cyclonedds_home` build-előfeltétellel + a build-context lépések dokumentálása/szkriptesítése
