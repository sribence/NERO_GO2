# Élő occupancy grid — perzisztencia + kiszervezett teszt (2026-09-17)

**Státusz: az inkrementális térkép-akkumuláció maga MÁR MEGVOLT (2026-09-05
óta éles) — ez a munka a meglévő logika kiszervezését, diszk-perzisztenciáját
és unit-tesztelését adta hozzá. Nem SLAM-relokalizáció, nem többszintű
térképezés — azok külön, nyitott TODO-elemek (ld. alul).**

Kapcsolódó korábbi napló: [15-munkamenet-naplo-2026-09-04.md](15-munkamenet-naplo-2026-09-04.md)
(a Hesai 90°-os extrinsic-korrekció felfedezése, offline `build_map.py`
prototípus). `TODO.md` nyitott elemei: "2D Occupancy Grid finomítás +
`level_id` cellánkénti címkézés" (rövid táv) és "Valódi relokalizáció (ICP
scan-match)... jelenleg szimulált/fix érték" (hosszú táv).

## Amit a mai session ELLENŐRZÖTT a kódban (nem feltételezett)

Mielőtt bármit írtunk volna, elolvastuk a tényleges jelenlegi állapotot:

1. **A `docker/mapping/build_map.py`** (2026-09-04 esti offline prototípus)
   egy egyszeri, offline futtatású script — egy `.jsonl` felvételből épít
   EGY statikus occupancy gridet, nem fut folyamatosan, nem perzisztál
   automatikusan.
2. **A tényleges ÉLŐ, folyamatosan akkumuláló térképező már létezik és
   üzemel** `docker/web_dashboard/app.py`-ban, 2026-09-05 óta:
   `_live_map_thread` → `_live_map_update_once` → log-odds Bresenham-
   frissítés (`LOGODDS_HIT`/`MISS`/threshold-ök), memóriában tartja a
   `_live_map_state["log_odds"]` tömböt AZ ELINDULÁS ÓTA, minden tick csak
   ráépít az előzőre — ez már pontosan az "időben felhalmozódó occupancy
   grid", amit a mai feladat kért. **Ez tehát NEM volt hiányzó, csak nem
   volt diszkre mentve.**
3. **A 90°-os Hesai extrinsic-korrekció** ugyanitt él, aktívan alkalmazva:
   `LIVE_MAP_YAW_OFFSET = math.radians(90)` (app.py, a "Élő occupancy grid"
   szekció eleje), felhasználva a `world_yaw = ryaw + LIVE_MAP_YAW_OFFSET`
   sorban a pontfelhő világ-koordinátába forgatásánál. **Nem nyúltunk hozzá
   — ez a 2026-09-04-i kalibráció eredménye, jelenleg helyesnek tekintjük,
   nem "javítottuk újra".**
4. **A `/live_map_data` route már létezett**, SSE-n 1 Hz-en, és már
   tartalmazta a teljes felhalmozott gridet (`width`/`height`/`resolution`/
   `origin_x`/`origin_y`/`data`) + a robot pózát — ez a route-kontraktus
   NEM változott, csak két új, opcionális mezővel bővült (ld. alul).

## Mi ÚJ készült el ma este

### 1. `docker/web_dashboard/lidar_mapping.py` (új fájl)

A log-odds/Bresenham/cella-konverzió + rács-levezetés kódja ki lett
szervezve app.py-ból egy önálló, Flask/robot-SDK-mentes modulba —
`world_to_cell`, `bresenham_update_logodds`, `grid_from_logodds`,
`integrate_scan` (a "egy scan beépítése a perzisztens log-odds-ba" teljes
lépés), `save_grid_snapshot_png`, `SnapshotScheduler`. Ok: `app.py`
importja azonnal háttérszálakat indít (DDS-kapcsolat, HTTP-lekérdezések) —
ezt egy teszt-futásnak SOSEM szabad megtennie, ld. a meglévő
`test_joint_safety.py` minta (az is külön modult importál, nem app.py-t).

`app.py`-ban `_live_map_update_once` most ezt a modult hívja
(`lidar_mapping.integrate_scan(...)`), a duplikált matek-kód törölve.

### 2. Periodikus PNG-mentés diszkre

`_live_map_thread` minden tick után meghívja `_live_map_maybe_save_snapshot()`-
et, ami egy `SnapshotScheduler`-rel (10 másodperces alapértelmezett
intervallum) eldönti, hogy kell-e menteni, és ha igen, a jelenlegi
felhalmozott gridet PNG-ként kiírja ide:

```
docker/web_dashboard/static/maps/live_map.png
```

(a meglévő `static/maps/demo_map.png` placeholder melletti, ugyanazon
statikus-asset konvenciót követve). Szürkeárnyalatos kódolás: ismeretlen
(-1) = szürke 127, szabad (0) = fehér 255, akadály (100) = fekete 0 — a
szokásos ROS/SLAM occupancy-grid vizuális konvenció. A mentés sosem dob
kivételt (try/except, `None` visszatérés hiba esetén) — egy átmeneti
diszkhiba nem véve le a háttérszálat.

### 3. `/live_map_data` bővítve két új, opcionális mezővel

A meglévő SSE-payload minden korábbi mezője változatlan; hozzáadva:
`snapshot_url` (`/static/maps/live_map.png` vagy `null`, amíg még nem
volt mentés) és `snapshot_saved_at` (unix timestamp vagy `null`). A
frontend (`showcase.html`) semmilyen módosítást nem igényel — a meglévő
mezőolvasása (`width`/`height`/`data`/stb.) érintetlen, az új mezőket
egyszerűen figyelmen kívül hagyja, amíg nincs hozzá UI.

### 4. Unit tesztek — `docker/web_dashboard/tests/test_lidar_mapping.py`

11 teszt, plain-assert stílus (ld. `mission-control/tests/test_watchdog.py`
mintája), szintetikus scan-adatokkal, valós LiDAR/robot nélkül:

- `world_to_cell` konverzió (origó, felbontás).
- Bresenham: végpont "occupied" irányba, útvonal "free" irányba mozdul,
  telítés a min/max-nál, tartományon kívüli végpont nem dob hibát.
- `grid_from_logodds` küszöbök (occupied/free/unknown határok).
- **`integrate_scan` — a tényleges "időben felhalmozódás" viselkedés**:
  egy szintetikus fal 20 sugárral egyszeri scan-ben occupied lesz, a
  köztes cellák free-vé válnak; egy fal TÖBB egymást követő scan-en át
  ismételt észlelése stabilan occupied-dé érik, míg egy EGYETLEN alkalommal
  látott zajpont nem éri el az "occupied" küszöböt ugyanabban a felhalmozott
  gridben — ez pont az a viselkedés, amit a log-odds megközelítés a
  2026-09-05-i naiv hit-counting helyett garantál.
- Tartományon kívüli pontok csendben kimaradnak (nem crash).
- `save_grid_snapshot_png` valódi fájlt ír (`tmp_path` fixture).
- `SnapshotScheduler` időzítés-logikája (fake clock, nincs valós várakozás).

Futtatás:

```bash
cd docker/web_dashboard
python -m pytest tests/test_lidar_mapping.py -q
# 11 passed
python -m pytest tests/ -q
# 44 passed (a meglévő 33 + ez a 11)
```

`python -m py_compile app.py lidar_mapping.py` is hiba nélkül lefut.

## Hogyan teszteld ma este hardver nélkül

1. `cd docker/web_dashboard && python -m pytest tests/test_lidar_mapping.py -v`
   — minden fenti eset egyenként látható.
2. Ha kedved van hozzá, indítsd el mock módban a teljes dashboardot
   (`MOCK_SDK=1 python app.py`), várj ~15 másodpercet (2× a 10s snapshot-
   intervallumnál), és nézd meg, hogy megjelenik-e
   `docker/web_dashboard/static/maps/live_map.png` — ez a mock SDK
   szintetikus pozíció/pontfelhő adatával megy át a TELJES úton
   (`_live_map_update_once` → `integrate_scan` → PNG-mentés), csak a
   `hesai_bridge` HTTP-hívás sikertelensége esetén (ha az a szolgáltatás
   nincs elindítva) a frissítés kimarad — ez esetben a snapshot a korábbi
   (esetleg "ready: False") állapotot mutatja, ami várható, nem hiba.

## Mit nézz meg holnap reggel, valódi Hesai LiDAR-ral

- **Nő-e a perzisztált térkép helyesen, ahogy a robot mozog?** — sétáltasd
  körbe a robotot egy ismert szobában, figyeld a `/live_map_data` SSE-t
  (vagy a showcase oldal LiDAR-panelét) és a
  `static/maps/live_map.png` időbélyegét (`snapshot_saved_at`) — a
  szoba-kontúrnak fokozatosan, összefüggően kell kirajzolódnia, nem
  "elárasztva" (ld. a 2026-09-04-i "elárasztott" 10778 vs 6374 cellás hiba,
  ami épp a hiányzó 90°-os korrekció miatt volt).
- **Még mindig helyesen van-e alkalmazva a 90°-os korrekció?** — a kód
  jelenlegi helye: `docker/web_dashboard/app.py`, `LIVE_MAP_YAW_OFFSET =
  math.radians(90)` konstans (az "Élő occupancy grid" szekció elején,
  kb. a `LIVE_MAP_RESOLUTION` konstans mellett), felhasználva
  `_live_map_update_once`-ban a `world_yaw = ryaw + LIVE_MAP_YAW_OFFSET`
  sorban. Ha a holnapi térkép megint "elárasztott"-nak tűnik, ELŐSZÖR ezt
  a konstanst és a szenzor tényleges felszerelési szögét vessd össze —
  NE tételezd fel újra a hibát, mérd meg.
- **Gyors forgásnál kimarad-e a frissítés a vártnak megfelelően?** —
  `LIVE_MAP_MAX_YAW_SPEED = 0.35 rad/s` felett a kód szándékosan kihagyja
  a tick-et (ld. app.py kommentje az odometria-csúszásról) — ha a robot
  gyorsan forog séta közben, a térkép NEM fog frissülni addig, ez a
  tervezett viselkedés, nem hiba.
- **A snapshot PNG valóban frissül-e a robot mozgása közben** (nem csak a
  legelső mentésnél áll meg) — nézd meg a fájl module-időbélyegét
  többször, néhány másodperc különbséggel.

## Amihez explicit NEM nyúltunk (szándékosan)

- **Valódi ICP scan-match relokalizáció** — a `TODO.md` hosszú távú
  listáján szereplő, jelenleg szimulált/fix konfidencia-jelző. Ha ehhez
  a részhez kell hozzáérni, csak jelezni, félkész implementációt NEM
  bevezetni (ld. a mai feladatkiírás explicit korlátozása).
- **Többszintű (`level_id` cellánkénti) térképezés** — a `TODO.md` rövid
  távú listáján szereplő finomítás, a jelenlegi élő térkép egy egyszintű,
  fix 20×20 méteres rácsot tart (`LIVE_MAP_SIZE_M`), nincs szint-detektálás
  ehhez a pipeline-hoz (az a `mission-control/mapping/` külön, sokkal
  fejlettebb stack-jében van meg — `StairDetector`/`MapStore`, ld. annak
  saját README-jét —, de az egy teljesen más, autonóm "wander and map"
  szolgáltatás, nem ez a live-dashboard occupancy grid, és a
  `mission-control` audit (2026-09-10) szerint élő roboton egyáltalán nem
  szabad futtatni jelenleg).
