# Egyrobot (Go2-only) waypoint + task-queue mission mód

**Státusz (2026-09-17 este): kész + 9 unit teszt zöld, MOCK_SDK=1 alatt
Flask-en át is végigfuttatva (submit → start → waypoint-haladás → task
végrehajtás → cancel), valódi roboton még sosem futott.**

## Hatókör — ez EXPLICIT csak egy Go2-re vonatkozik

Ez **nem** a multi-robot (Xavier Pickerbot + Go2) közös mission felület — az
a `TODO.md` "Multi-robot `core` refaktor" pontja szerint előfeltételként a
`mission-control/core/service.py` szétbontását igényli (`/robots/{id}/state`,
`ROBOT_ID` env-változó pillérenként), **ami még nem történt meg**. Idézet a
`TODO.md`-ből:

> Előfeltétel a lenti "multi-robot `core` refaktor" — anélkül a Xavier csak
> egy második, párhuzamos, nem összekötött stack maradna.

Ez a mai munka **szándékosan** ki van véve abból a feladatból: nem nyúl a
`mission-control/`-hoz, nem köt be Xavier Pickerbot-ot, kizárólag a
`docker/web_dashboard/app.py`-ban MÁR meglévő egypontos navigáció
(`/api/navigate`) + akció-végpontok (`/run_action/<name>`) fölé épít egy
waypoint-sort + hozzá tartozó task-listát, egyetlen Go2-re.

## Mi készült

- [`docker/web_dashboard/mission.py`](../docker/web_dashboard/mission.py) —
  `MissionRunner` osztály. Dependency-injection: semmit nem tud Flaskről,
  DDS-ről vagy `sport_client`-ről, csak a neki átadott függvényeket hívja.
  Ez a lényeg, ami biztonságilag számít: **minden mozgás-parancs a meglévő
  armed/watchdog/E-stop kapun megy át**, mert a `navigate_to_fn` és
  `cancel_navigate_fn` pontosan azt az `_nav_state`-et írja, amit az
  `/api/navigate` és `/api/navigate/cancel` route is.
- `docker/web_dashboard/app.py` bekötés (nem módosítja a meglévő
  `/api/navigate*` route-ok viselkedését, csak kiszervez belőlük 3 kis
  helper-függvényt a mission-runner számára):
  - `_navigate_single(x, y)` — egypontos navigáció indítása (ua. `_nav_state`).
  - `_cancel_navigation()` — ugyanaz a leállítás, mint `/api/navigate/cancel`
    (`_safe_stop_move` fallback, ld. `run_action`/`follow` kódnál is).
  - `_nav_reached(x, y)` — `True`, ha a legutóbbi navigáció-ciklus PONTOSAN
    ezt a célpontot érte el (`last_status.type == "reached"` ÉS nincs aktív
    `target`) — tudatosan **nem** elég, hogy `target is None`, mert
    cancel/estop is `None`-ra állítja, azt itt nem szabad "megérkezés"-nek
    félreérteni.
  - `_mission_run_pose_action(name)` / `_mission_lie_down()` — a meglévő
    `_actions()` dict-ből hívja a `wave`/`sit`/... vagy `lay_down`
    (`StandDown`) akciót, szinkron (nem külön szálban, mert a mission-runner
    saját maga már háttérszálban fut).
  - Négy új route: `POST /api/mission` (beküldés), `POST /api/mission/start`
    (indítás), `POST /api/mission/cancel` (megszakítás), `GET
    /mission_status` (állapot lekérdezés).
- Mellékesen javítva: a `static/photos/` mappa hiányzott a repóból (csak
  `static/maps/` volt), ezért `_capture_photo()` mindig `FileNotFoundError`-t
  dobott volna, amint bárki tényleg meghívja — ez eddig rejtve maradt, mert
  semmi nem hívta rendszeresen. `os.makedirs(..., exist_ok=True)` most már
  létrehozza, ha kell.
- [`docker/web_dashboard/tests/test_mission.py`](../docker/web_dashboard/tests/test_mission.py)
  — 9 unit teszt, mind zöld:
  `python -m pytest docker/web_dashboard/tests/test_mission.py -v`

## Task-típusok (fix készlet)

| task | mit csinál | armed-check? |
|---|---|---|
| `pose` | meglévő akció lefuttatása (`task_param`: pl. `"wave"`, `"sit"`, alapérték `"sit"`) | igen |
| `photo` | frame mentése `/camera_feed`-ről (`_capture_photo`), fájlnév `photo_<timestamp>_wp<id>.jpg` | nem (nem mozgat) |
| `lie_down` | `StandDown` (`lay_down` akció) | igen |
| `charge_dock` | **STUB** — logol `"would dock here"`, `ok: False`-t ad vissza | nem (nem mozgat) |

**`charge_dock` KRITIKUS megjegyzés:** ebben a repóban **nincs** valódi
dokkoló-station integráció (ellenőrizve: `grep -rn "dock\|charg" -i
docker/web_dashboard/*.py` nem ad hardware-kontextusú találatot). A
`charge_dock` task ezért tudatosan egy stub, ami sosem állíthat sikert, amit
nem tud igazolni — a `mission.py` a `_execute_task`-ban explicit felülírja
`ok`-t `False`-ra a `charge_dock` ágon, **még akkor is**, ha egy jövőbeli
egyedi `charge_dock_fn` optimista `True`-t adna vissza (ld.
`test_charge_dock_custom_fn_cannot_force_success_either` a teszt-fájlban).
Amikor a valódi dokkoló-integráció megépül, ezt a viselkedést tudatosan kell
megváltoztatni, nem véletlenül.

## Biztonsági garanciák

- **Armed-check minden mozgás-parancs előtt.** `MissionRunner._run()`
  ellenőrzi `is_armed_fn()`-t (a) minden waypoint navigálása előtt, (b) a
  megérkezés utáni task végrehajtása előtt is. Ha valaki (operátor,
  watchdog auto-disarm 30s inaktivitás után, vagy E-stop) közben disarmol,
  a küldetés **azonnal** `aborted` állapotba kerül, a következő waypointra
  **nem** megy tovább — ezt a `test_disarm_mid_mission_stops_immediately_...`
  teszt igazolja.
- **Abort minden lépés között ellenőrizve.** Egy `threading.Event` (abort
  flag), amit a `/api/mission/cancel` route állít be — a háttérszál a
  navigáció-várakozás pollozó ciklusában (0.2s-enként) és minden
  waypoint-váltásnál ellenőrzi. `abort()` szinkron hívja a
  `cancel_navigate_fn`-t is, hogy a mozgás akkor is azonnal megálljon, ha a
  szál épp egy hosszú várakozásban van.
- **Nincs saját mozgás-útvonal.** A mission-runner sosem hívja a
  `sport_client`-et közvetlenül — csak az app.py MÁR meglévő,
  armed/watchdog-védett `_navigate_single`/`_mission_run_pose_action`/
  `_mission_lie_down` függvényeit, amik ugyanazok a függvények, amiket a
  kézi joystick és a `/api/navigate` is használ.
- **Waypoint-timeout (60s).** Ha egy célpont sosem éri el a "reached"
  állapotot (elakadt robot, hibás pozíció-adat), a küldetés `error`
  állapotba kerül, nem marad örökre "running"-ban.

## Hogyan teszteld holnap reggel

1. **Először MOCK_SDK=1, robot nélkül.** Ez a mai teszt-kör pontosan ezt
   tette:
   ```
   cd docker/web_dashboard
   MOCK_SDK=1 python app.py
   ```
   Majd egy másik terminálból (vagy a `test_mission.py` unit tesztjei, amik
   nem indítanak Flaskot, hanem a `MissionRunner`-t sima Python fake-eken
   át tesztelik — ez a gyors, determinisztikus kör):
   ```
   python -m pytest docker/web_dashboard/tests/test_mission.py -v
   ```
   Végponti (Flask-es) füstteszt egy waypoint-tal:
   ```
   curl -X POST http://localhost:5002/arm
   curl -X POST http://localhost:5002/api/mission -H "Content-Type: application/json" \
     -d '{"waypoints":[{"id":1,"x":1,"y":0,"task":"photo"},{"id":2,"x":2,"y":0,"task":"charge_dock"}]}'
   curl -X POST http://localhost:5002/api/mission/start
   curl http://localhost:5002/mission_status   # ismételve, amíg "status":"done"
   ```
   **Abort-tesztet ELŐBB futtasd le, mint bármilyen több-waypointos éles
   futást** — indíts egy 2+ waypointos missziót, várj ~0.5s, hívd meg
   `/api/mission/cancel`-t, és ellenőrizd `/nav_status`-on + `/mission_status`
   -on, hogy a robot (mock módban: a szimulált navigáció) tényleg megállt,
   és a második waypointra sosem ment ki parancs.

2. **Csak ha az abort megbízhatóan működik MOCK_SDK=1 alatt**, térj át
   `ROBOT_BACKEND`/valós SDK módra. Első éles futás **egyetlen, közeli,
   szabad terepen lévő waypointtal**, `pose`/`photo` taskkal (NE
   `lie_down`-nal vagy több waypointtal elsőre). Az E-stop
   (`POST /api/estop`) legyen kézre eső egy másik terminálban/böngésző-fülön
   végig a teszt alatt.

3. Csak ezután próbálj több-waypointos, vegyes task-listát élesben.

## Amit ez a munka NEM csinál (tudatosan)

- Nem köt be Xavier Pickerbot-ot és nem nyúl a `mission-control/`-hoz.
- Nem implementál valódi dokkolás-detektálást/dokkolás-vezérlést
  (`charge_dock` marad stub, amíg a hardware-integráció meg nem épül).
- Nem ad operátori UI-panelt a küldetés-összeállításhoz (csak a 4 REST
  route) — ha kell egy kattintható waypoint-szerkesztő a térképen, az egy
  külön front-end feladat a meglévő `/live_map_data`/kattintós-navigáció
  UI-ra épülve.
