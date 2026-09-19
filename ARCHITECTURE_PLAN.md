> **[Klón: C:SERSSERNERO_GO2 � SLAM/DOCS áG]**
# 🏗️ NERO GO2 — Architekturális Refaktorálási & Moduláris Terv

> **Cél:** A kód szétbombázása nélkül, fokozatosan átállni egy tisztább, AI-barát, könnyen tesztelhető és moduláris architektúrára.

---

## 1. Jelenlegi Architekturális Szűk Keresztmetszetek
1. **Monolitikus Script-ek:** A `benchmark_3d.py` és a korábbi html generálók túl sok felelősséget (adatbetöltés, ICP számítás, HTML template összefűzés) egyetlen fájlban kezeltek.
2. **Keményen Kódolt Konfigurációk:** A szenzor kalibrációs értékek (`0.99x` gyro skála, `96.0°` yaw offset, IP-címek) több scriptben szétszórva szerepelnek.
3. **Élő Robot Függőség a Tesztelésnél:** Nehéz volt tesztelni a felületet fizikai robot nélkül.

---

## 2. Javasolt Moduláris Szerkezet (Refaktorálási Lépések)

### A. Konfiguráció Központosítása (`config/`)
Hozzunk létre egy központi YAML/JSON konfigurációs fájlt, ahonnan minden modul felolvassa a beállításokat:
```
c:\Users\user\NERO_GO2\config\
├── sensors.yaml         # Hesai offsetek, Gyro skála, szögkorrekciók
├── network.yaml         # IP-címek, portok, Docker kapcsolódások
└── slam_params.yaml     # KISS-ICP voxel méret, max_range, min_range
```

### B. Robot API Interfész Leválasztása (`core/robot_interface/`)
Egy absztrakt Python interfész (`RobotBridge`) bevezetése, amely mögött két megvalósítás futhat:
1. `LiveRobotBridge` (Valós CycloneDDS + UDP stream)
2. `MockRobotBridge` (Pre-recorded `.jsonl` adatsorok visszajátszása)
*Előny:* Az AI és a frontend tesztelhető fizikai robot jelenléte nélkül is.

### C. Ágens-Konfigurációk & Promptok Mappája (`agents/`)
Az AI ágensek speciális feladatainak (pl. SLAM paraméter-hangoló, diagnosztikai ellenőr) promptjait és szabályait különítsük el:
```
c:\Users\user\NERO_GO2\agents\
├── slam_tuner_prompt.md
├── hardware_diagnostics_prompt.md
└── safety_guard_rules.md
```

### D. Tiszta Végpont-Separálás a Backendben (`docker/web_dashboard/`)
- `routes/telemetry.py` — SSE adatszórás
- `routes/slam.py` — 3D pontfelhők és 2D térképek
- `routes/control.py` — Mozgásvezérlő parancsok

---

## 3. Ütemezési Terv a Refaktorálásra
1. **1. Lépés:** Konfigurációs fájlok kiszervezése (`config/`).
2. **2. Lépés:** `MockRobotBridge` és `LiveRobotBridge` interfész elkészítése.
3. **3. Lépés:** Végpontok moduláris bontása.
*Minden lépés végén automatikus visszafele-kompatibilitási tesztet futtatunk.*
> **[Klón: C:devNERO_GO2 — mission-control ág]**
# 🏗️ NERO GO2 (dev/mission-control) — Architekturális & Multi-Agent Terv

> **Cél:** a meglévő, már jól szeparált `mission-control` architektúrát felkészíteni
> több párhuzamos AI-ágens (cavecrew-stílusú, token-spórolós) bevonására, és
> előkészíteni a most felvett TODO-kat (YOLO, multi-robot, joint-vezérlés) anélkül,
> hogy szét kellene bombázni a meglévő szerkezetet.

---

## 1. Jelenlegi állapot — ez már jól áll (nem kell újraírni)

A testvér-klón `ARCHITECTURE_PLAN.md`-je 3 hiányosságot azonosított a fő repóban
(monolitikus scriptek, szétszórt konfig, élő robot-függőség tesztelésnél). Itt,
a `mission-control` ágban mindhárom **már megoldva**:

1. **Robot API interfész leválasztva** (`mission-control/core/`): `mock_client.py`,
   `live_client.py`, `remote_client.py` — pontosan a testvér-terv B. pontjában javasolt
   `MockRobotBridge`/`LiveRobotBridge` mintázat, `ROBOT_BACKEND` env-változóval kapcsolva.
2. **Konfiguráció központosítva** pillér-szinten: `CONVENTIONS.md` a mérvadó forrás
   portokra, env-változókra, Dockerfile-mintára, event-bus csatornanevekre.
3. **Tesztelhető élő robot nélkül**: mind a 9 pillér egyenként igazoltan futott
   `ROBOT_BACKEND=mock` alatt, `demo.py` LAN-on is megnyitható.

**Ebből következik:** ez a terv nem újraszervezést ír le, hanem a meglévő,
bevált pillér-mintázat **kiterjesztését** a most felvett feladatokra.

---

## 2. Agent-olvasási határok (token-spórolás — ÚJ szabály)

A repó már eleve pillérenkénti `README.md`-kre van bontva — ezt formalizáljuk
explicit ágens-szabályként, hogy egy jövőbeli multi-agent futás ne olvassa be
feleslegesen a teljes repót minden egyes al-feladathoz:

| Feladat típusa | Amit az ágens olvasson | Amit NE olvasson be |
|---|---|---|
| Egy pillér belső logikájának módosítása | `<pillér>/README.md` + `CONVENTIONS.md` | `AUDIT-2026-09-10.md`, `PROJECT_BRIEF.md` |
| Új pillér vagy multi-robot refaktor | `PROJECT_CONTEXT.md` + `CONVENTIONS.md` + érintett pillérek README-jei | a többi, nem érintett pillér forráskódja |
| Biztonsági/safety kérdés | `AUDIT-2026-09-10.md` releváns P0/P1 szakasza (nem a teljes fájl) | — |
| Új munkamenet kontextus-felvétele | `PROJECT_CONTEXT.md` → `PROJECT_BRIEF.md` → `STATUS.md` (ebben a sorrendben) | — |

**Javasolt `agents/` mappa** (még nincs létrehozva — a testvér-terv is csak
javasolta a saját repójában, ott sem épült meg még):

```
mission-control/agents/
├── pillar_builder_prompt.md       # 1-2 fájlos, egy pilléren belüli módosításhoz
├── multi_robot_refactor_prompt.md # a core/service.py /robots/{id}/state bontásához
├── safety_reviewer_prompt.md      # P0-szintű safety-review minden mozgás-érintő diffhez
└── yolo_integration_prompt.md     # yolo_detector.py bekötése sensors/multicam pillérbe
```

Minden prompt-fájl elején kötelező: pontosan mely fájlokat olvashatja be az ágens,
és mit TILOS módosítania (pl. `CONVENTIONS.md` portszámai, `core/` biztonsági zárak).

---

## 3. Konkrét kiterjesztési pontok a TODO-khoz

### A. YOLO integráció
- Új pillér-alfájl: `mission-control/sensors/yolo_client.py` vagy `multicam/yolo_client.py` — a testvér-klónbeli `docker/realsense_bridge/yolo_detector.py` logikájának átemelése, `CONVENTIONS.md` Dockerfile-mintájával konténerbe téve.
- **Nem** kap saját portot a `CONVENTIONS.md` port-táblájában — a meglévő `sensors` (9105) vagy `multicam` (9106) végpontján belül egy új route.

### B. Multi-robot `core` refaktor
- `core/service.py`: `/state` → `/robots/{id}/state`, `/move` → `/robots/{id}/move`, stb.
- Minden pillér kap egy `ROBOT_ID` env-változót (alapérték: `go2`), amit minden `core`-hívásba belefűz.
- Xavier Pickerbot Mini ehhez egy **második** robot-klienst igényel (`core/xavier_client.py`) — a Xavier saját, ROS Noetic-alapú stackjéhez illesztve, nem a Go2 DDS/WebRTC útján.
- Migrálás lépésről lépésre: 1) `core` API bővítése backward-compatible módon (régi útvonalak `robots/go2/...`-ra alias-olva), 2) egy pillér átállítása és tesztelése, 3) a többi pillér sorban.

### C. Joint-szintű (`LowCmd`) kézi vezérlés + trükk-betöltés
- Külön, izolált al-modul (pl. `mission-control/lowlevel/`), **nem** a meglévő `core` mozgás-útvonalába ágyazva — hogy egy hibás alacsony-szintű parancs ne tudja megkerülni a meglévő `is_armed()`/watchdog/sebességkorlát védelmet.
- Első lépés mindig kutatás (`unitree_sdk2py` `LowCmd`/`LowState` API, URDF joint-limitek), nem kód — ld. TODO.md.

---

## 4. Ütemezési terv

1. **1. lépés:** `agents/` mappa + prompt-sablonok létrehozása (ez a terv 2. szakasza).
2. **2. lépés:** YOLO integráció a `sensors`/`multicam` pillérbe (legkisebb kockázat, nincs mozgás-érintettség).
3. **3. lépés:** Multi-robot `core` refaktor, előbb csak Go2-vel (API-bővítés, Xavier még nem kötve rá).
4. **4. lépés:** Xavier Pickerbot Mini bekötése a bővített `core`-ra.
5. **5. lépés (safety-review kötelező):** joint-szintű vezérlés + trükk-betöltés kutatása, majd izolált `lowlevel/` modul.

*Minden lépés végén: `python -m pytest tests -q` a meglévő 20 regressziós teszttel + a lépéshez tartozó új tesztek.*
