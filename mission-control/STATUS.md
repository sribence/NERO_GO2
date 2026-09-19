# mission-control — állapot / futtatási referencia

_Utolsó frissítés: 2026-09-10_

## Rendszer elérési útvonala

- **Repó (lokális klón, ezen a Windows gépen):** `C:\dev\NERO_GO2`
- **Ez a modul:** `C:\dev\NERO_GO2\mission-control`
- **GitHub eredeti repó:** `https://github.com/sribence/NERO_GO2`
- **Konvenciók / interfészek:** `C:\dev\NERO_GO2\mission-control\CONVENTIONS.md`
- **Architektúra-leírás:** `C:\dev\NERO_GO2\mission-control\README.md` és `C:\dev\NERO_GO2\docs\16-mission-control-terv.md`

## Jelenlegi státusz

Mind a 9 pillér (`core`, `mapping`, `navigation`, `orchestration`, `sensors`, `multicam`, `audio`, `blackbox`, `remote`, `digital-twin`) elkészült és **egyenként, plain Python-folyamatként tesztelve `ROBOT_BACKEND=mock` mellett**. A `core` HTTP-proxy rétegét (`/state`, `/move`, `/camera_frame`, `/lidar_points`, `/arm`) is leteszteltem két külön folyamat között — a robot-állapot ténylegesen megosztott.

> ⚠️ **A „tesztelve" itt mock-ot jelent, nem élő robotot.** A 2026-09-10-i audit
> (`AUDIT-2026-09-10.md`) 12 P0 hibát talált, amiből 5-öt futtatással bizonyított — köztük
> olyanokat, amiket a mock szerkezetileg elrejtett. Mind a 12 javítva, 20 regressziós teszt
> őrzi őket (`python -m pytest tests -q`). Az élő (`ROBOT_BACKEND=live`) út továbbra sem
> futott valódi roboton, és két telemetria-mezőnév **ELLENŐRIZENDŐ** az első robotos
> menetben, mozgatás előtt.

## A felület megnézése robot és Docker nélkül

```powershell
cd C:\dev\NERO_GO2\mission-control
python demo.py
```

Kiírja a localhost- és a LAN-címet; a LAN-cím telefonról is megnyitható ugyanarról a WiFi-ről.
Ha a telefon nem éri el, a Windows tűzfalat kell egyszer engedélyezni (rendszergazdaként):

```powershell
New-NetFirewallRule -DisplayName "mission-control demo 9110" -Direction Inbound -LocalPort 9110 -Protocol TCP -Action Allow -Profile Private
```

## Tesztek

```powershell
cd C:\dev\NERO_GO2\mission-control
python -m pytest tests -q
```

**Blokkolva:** a teljes `docker compose up --build` (mind a 9 konténer egyszerre) — a Docker Desktop telepítve van ezen a gépen, de a WSL2/"Virtual Machine Platform" Windows-funkció nincs bekapcsolva, ennek engedélyezése admin-jogosultságot + újraindítást igényel, amit egyelőre nem tudsz megcsinálni. Amint ez megoldódik, a lenti Compose-parancs változtatás nélkül futtatható.

## Futtatási lehetőségek

### 1. Teljes stack, Docker Compose-zal (ajánlott, ha van Docker) — jelenleg blokkolva

```powershell
cd C:\dev\NERO_GO2\mission-control
docker compose up --build
```

Robot nélkül (`ROBOT_BACKEND=mock`, alapértelmezett) minden pillér egy közös, megosztott mock-robot-állapotot lát (a `core` konténeren keresztül). Élesben, a Jetsonon:

```bash
ROBOT_BACKEND=live WEBRTC_BRIDGE_URL=http://192.168.123.18:8000 docker compose up --build
```

### 2. Pillérenként, plain Pythonnal (Docker nélkül is működik — ezt teszteltük élesben)

Minden pillérnek saját `requirements.txt`-je van, a `core/`-t is telepíteni kell mellé:

```powershell
cd C:\dev\NERO_GO2\mission-control\<pillér>
python -m venv venv
venv\Scripts\pip install -r requirements.txt -r ..\core\requirements.txt
$env:PYTHONPATH = "..\core"
venv\Scripts\python app.py
```

Ahol `<pillér>` = `core`, `mapping`, `navigation`, `orchestration`, `sensors`, `multicam`, `audio`, `blackbox` (a `digital-twin`-nél `server.py` az indítófájl, a `remote`-nál nincs saját HTTP szolgáltatás, csak a `log_shipper.py` script + a `docker-compose.fragment.yml`).

Ha több pillért futtatsz egyszerre így (nem Docker Compose-ban), mindegyiknek külön portot ad a `CONVENTIONS.md` (9101-9110), és a `ROBOT_CLIENT_MODE=remote` + `CORE_URL=http://localhost:9101` env-változókkal érik el ugyanazt a `core`-ban futó megosztott robot-állapotot — pontosan úgy, ahogy én is leteszteltem.

### 3. Csak egy pillér, elszigetelt teszteléshez

Egyetlen pillér `ROBOT_CLIENT_MODE` nélkül (alapértelmezett: `local`) a saját, önálló mock-robotjával indul — nem kell hozzá se Docker, se a `core` szolgáltatás. Ez az a mód, amiben az építő agentek is leellenőrizték az egyes pillérek belső logikáját (pl. `mapping` frontier-exploration, `navigation` A*, `orchestration` teljes task-lánc).

## Tesztelési módok

| Env-változó | Értékek | Mit vált |
|---|---|---|
| `ROBOT_BACKEND` | `mock` (alapértelmezett) / `live` | A `core` (vagy egy önálló, `local` módban futó pillér) szintetikus vagy valódi (DDS+WebRTC) robotot használ-e. |
| `ROBOT_CLIENT_MODE` | `local` (alapértelmezett) / `remote` | A pillér saját, elszigetelt robot-klienst indít-e (`local`), vagy a `core` szolgáltatás HTTP API-ján keresztül egy **megosztott** robot-állapotot ér el (`remote`) — ez utóbbi a helyes mód, ha több pillért futtatsz egyszerre (Compose vagy kézi multi-processz). |
| `CORE_URL` | pl. `http://core:9101` (Compose-ban) / `http://localhost:9101` (kézi futtatásnál) | Csak `ROBOT_CLIENT_MODE=remote` esetén releváns — hova küldje a `remote_client.py` a kéréseket. |

### Gyors ellenőrző parancsok (a `core` szolgáltatás fut, pl. `python core\app.py` vagy Compose-ban)

```bash
curl http://localhost:9101/state
# az allapotvaltoztato vegpontok tokent kernek (MC_API_TOKEN), az /estop soha nem:
curl -X POST http://localhost:9101/arm -H "X-MC-Token: $MC_API_TOKEN"
curl -X POST http://localhost:9101/estop
curl -X POST http://localhost:9102/explore/start
curl http://localhost:9102/map
curl -X POST http://localhost:9103/goto -d '{"x":1,"y":1}' -H 'Content-Type: application/json'
curl -X POST http://localhost:9104/task -d '{"steps":[{"goto":[1,1]}]}' -H 'Content-Type: application/json'
curl -X POST http://localhost:9105/sensor/photo
curl http://localhost:9106/cameras
curl -X POST http://localhost:9107/audio/play/test
curl http://localhost:9108/buffer/status
```

`digital-twin` böngészőben: `http://localhost:9110/`

## Következő lépés, amint Docker/WSL2 rendelkezésre áll

```powershell
cd C:\dev\NERO_GO2\mission-control
docker compose up --build
docker compose ps
```

Utána a fenti "Gyors ellenőrző parancsok" mindegyike ugyanígy fut, csak most már mind a 9 konténer egyszerre, közös hálózaton.
