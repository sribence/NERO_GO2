# Capability Showcase — projektleírás

**Indult:** 2026-09-03 este, robot nélkül. **Cél:** egy 45-90+ perces órai/prezentációs bemutató-eszköz egyetemistáknak/felnőtteknek — nem játékos, hanem **műszaki-adatgazdag, "digitális iker"-jellegű** kirakat a robot mozgásáról, ízületeiről, szenzorairól. Ebből nőhet ki később a teljes oktatási csomag (ld. [11-oktatocsomag-terv.md](11-oktatocsomag-terv.md), [12-taszklista.md](12-taszklista.md), és a Xavier Pickerbot Mini "Akadémia"-mintája: `xavier-pickerbot/docs/06-sajat-projekt-akademia.md`).

## Mi ez most, és mi nem

**Ez a dokumentum a ma esti, robot nélküli munka rögzítésére való.** A teljes felvetett vízió (lásd lent, "Későbbi fázisok") jóval túlnő a mai kereten — SLAM, feladat-végrehajtás, objektumkövetés, hőkamera mind **valós robot-adatot igényel**, ezért azok csak tervként/architektúraként készülnek el ma, kód nem.

Ami ma este ténylegesen elkészül, tesztelve: egy **3D digitális iker "showcase" oldal**, ami a meglévő `web_dashboard` mellé kerül (`/showcase` route), a `mock_robot` szintetikus adatával hajtva — így robot nélkül is fejleszthető/bemutatható, élesben pedig ugyanaz a kód a valós DDS-adatra kapcsolva fut majd.

## Architektúra-döntés: egyszerűsített, de valós-geometriájú 3D modell

A hivatalos Unitree Go2 URDF (`unitreerobotics/unitree_ros/robots/go2_description/`) DAE-mesh-fájljait NEM töltjük be közvetlenül (extra konverzió/CORS/méret-komplexitás egy esti darabhoz) — **a "legegyszerűbb hozzáállás" elve alapján** helyette a valós URDF-ből kiolvasott ízület-offszetekkel, tengelyekkel és forgáshatárokkal (`<origin>`, `<axis>`, `<limit>`) építünk egy primitívekből (doboz törzs, kapszula csípő/comb/lábszár) álló, arányhelyes vázmodellt three.js-ben. Ez garantáltan elkészül és tesztelhető ma este, és a mozgás/geometria valódi, nem kitalált — csak a vizuális "bőr" (mesh-textúra) hiányzik, amit később, ha indokolt, rá lehet cserélni a valódi DAE-kra.

12 forgó ízület (revolute joint), lábanként 3 (hip/thigh/calf) × 4 láb (FL/FR/RL/RR) — ez pontosan megfelel a robot natív `LowState_.motor_state[0..11]` tömbjének (ld. [[project_go2_robot_system_map]] memória, `unitree_sdk2py` IDL).

## Ma este kész (💻)

- [x] `web_dashboard/app.py` — `_init_mock_sdk()` 12-motoros adatra, teljes póz-repertoárral (`_SHOWCASE_SEQUENCE`); `/showcase` + `/showcase_data` route; `DATA_SOURCE` mock/live jelölő
- [x] `web_dashboard/templates/showcase.html` — three.js 3D vázmodell + élő HUD-panelek
- [x] Teljes demo-koreográfia: Állás / Séta / **Integetés** / Ülés / "Szív"-köszöntés (stilizált, nem motion-captured — a valós SportClient-mozdulatok pontos trajektóriája nem ismert, ez explicit jelölve a kódban)
- [x] Élő kamera-panel (mock feed) + LiDAR-pontfelhő a 3D térben, forgó sweep-sugárral és távolság-alapú színezéssel
- [x] Forrásolt "képesség-legenda" panel (kutató-agenttel összeállítva, URDF-ből igazolt vs. kereskedelmi forrás jelöléssel)
- [x] **2026-09-03 éjszaka, 5-szerepű (marketing/tudományos/kutatói/oktatói/UX) workflow-brainstorm** két körben + szintézis — ebből épült be:
  - Globális MOCK/LIVE adatforrás-jelölő + "bizalom-index" (kritikus tudományos hitelesség — semmilyen adat nincs forrásjelölés nélkül)
  - Cold-open boot-szekvencia
  - CoM + támasztó-poligon élő stabilitás-vizualizáció (statikus vs. dinamikus stabilitás)
  - Élő teljesítményfelvétel-számítás (P=τ×ω, véges differenciával becsült ω-ból) + integrált Wh-számláló
  - IMU mesterséges horizont widget (repülőgép-HUD-stílus)
  - Gait-állapotgép diagram élő kiemeléssel
  - Ember-vs-robot érzékelés kontraszt-sáv
- [x] Böngészős verifikáció + screenshotok

### Ma este NEM készült el (a workflow-szintézis listájáról, jövőbeli kör anyaga)

- Vezetett "képesség-lépcső" 4-fázisú lecke-állapotgép (oktatói mód)
- Prezentátori cheat-sheet overlay (P billentyű)
- Hibaszimulációs demo-gomb (fault injection)
- Session debrief záró képernyő
- Kattintható izület-fókusz/inspect mód kamera-tweenekkel
- Panel-elrendezés memória (localStorage)

Ezek nem kerültek elvetésre — a workflow végső szintézise (`docs/14-capability-showcase-projekt.md` melletti workflow-futás naplója) tartalmazza a teljes, priorizált listát, ha a projekt folytatódik.

## Későbbi fázisok (🤖 — robotnál folytatandó, csak tervezve)

1. **Környezeti érzékelés bővítése** — valós idejű képmanipuláció, 3D pontfelhő a `webrtc_bridge`-ből, jövőbeli USB hőkamera integrációja
2. **Térbeli tájékozódás / SLAM** — üres térkép, Hesai LiDAR-ral térképezés, kézi VAGY automata ("robotporszívó-szerű") mód — a robot már rendelkezik saját `graph_pid_ws`/`QT_Server` SLAM-stackkel (ld. [05-egyedi-slam-stack.md](05-egyedi-slam-stack.md)), ezt kell feltérképezni/felhasználni, nem nulláról építeni
3. **Feladat-végrehajtás a térben** — "menj X pontra", "vegyél fel Y pózt", fotó/hangminta/hőkamera-kép/3D-fotó egy objektumról, egyszerű feladat-sor/queue
4. **Kapcsolható viselkedésmódok** — objektum-elkerülés be/ki, kamerás objektum-kijelölés+követés
5. **Összekötés a showcase-dashboarddal** — a mai 3D digitális iker mint a projekt végleges "kirakata", ami alá ez az egész rendszer épül

## Nyitott kérdések (jövőbeli, robotnál eldöntendők)

- Hőkamera: konkrét USB-modell még nincs kiválasztva/beszerezve
- SLAM automata mód: mennyire "robotporszívó-szerű" legyen (teljes autonóm lefedettség-térképezés) vs. csak pontnavigáció — ez UX-döntés, robotnál, valós SLAM-teszt után dönthető el érdemben
