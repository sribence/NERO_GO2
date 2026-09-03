# mock_robot — robot nélküli fejlesztői környezet

2026-09-03: a robot fizikailag nem volt elérhető, de a fejlesztést folytatni kellett — ez a modul erre a problémára a tartós megoldás, nem csak egy esti pótcselekvés.

## Miért kell ez

A Go2 EDU egy drága, nehezen pótolható, fizikailag megosztott hardver (ld. [00-BIZTONSAGI-SZABALYOK.md](../../docs/00-BIZTONSAGI-SZABALYOK.md)). Eddig **minden** `web_dashboard`/`webrtc_bridge` fejlesztés a robotra várt — ha nincs robot (kikapcsolva, elrakva, valaki más használja, nincs otthon), a fejlesztés is leáll. Ez strukturális probléma, nem egyszeri kellemetlenség.

A `mock_robot` a `webrtc_bridge` HTTP API-jának **pontos másolata**, szintetikus (kitalált, de valósághűen mozgó) adattal:
- `/health`, `/camera.jpg` (egy egyszerű, animált szintetikus kép), `/lidar` (egy kör alakú ponthalmaz), `/lidar_state`, `/state` (oszcilláló feszültség/áram/hőmérséklet/sebesség)

A `web_dashboard` `app.py`-jában egy `MOCK_SDK=1` env-változó egy `_FakeSportClient`-et használ a valódi `unitree_sdk2py` helyett — ugyanazokkal a metódusnevekkel (`Move`, `RecoveryStand`, `StandDown`, `Hello`, `Heart`, `Sit`), csak logol, nem küld semmit sehova. **Az `app.py`-ban ez az egyetlen elágazás** — a route-ok, a joystick-logika, a frontend semmit nem tud a különbségről.

## Használat

**Helyben (Python, gyors iterációhoz):**
```bash
cd docker/mock_robot && python mock_bridge.py          # 5001-es port
cd docker/web_dashboard && MOCK_SDK=1 WEBRTC_BRIDGE_URL=http://localhost:5001 python app.py   # 5002-es port
```
Nyisd meg: http://localhost:5002/

**Dockerrel:**
```bash
cd docker/mock_robot && docker compose up --build
```

## Amit ez NEM helyettesít

Ez a UI/UX-fejlesztésre és a joystick/arm-logika tesztelésére való — **nem** teszteli a valós WebRTC-kapcsolatot, a valós DDS-discovery-t, vagy a robot tényleges fizikai reakcióját. Minden, ami a valós robot API-viselkedésétől függ (pl. a `webrtc_bridge`/`web_dashboard` élő integrációs tesztjei), továbbra is csak a robotnál végezhető el — ld. [docs/12-taszklista.md](../../docs/12-taszklista.md) 🤖-jelölt taszkjai.
