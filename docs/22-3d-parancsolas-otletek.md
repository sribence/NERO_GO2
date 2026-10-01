# 3D parancsolás — ötletek és terv (OmniView)

Cél: a robotot az OmniView 3D-terében parancsolni: „fuss ide max sebességgel”, „ugrálj idáig”, „tervezz útvonalat”, „figyeld azt az embert”.
Alap: `omni` (:9114), `safety_guard` (:9115), `navigation` (A* + `nav_local` DWA), `mapping`, `mc_motion` (`Move`, `/action/*`: `FrontJump`, `FrontPounce`, `Hello`, `Dance1/2`, `Stretch`, …).
**Minden mozgás a `safety_guard`-on át megy. Ez minden ötletre érvényes.**

---

## 1. Mai korlátok (kiindulás)

| Mi | Érték / állapot | Forrás |
|---|---|---|
| `mc_motion` sebességplafon | `MAX_VX=0.6`, `MAX_VY=0.3`, `MAX_VYAW=0.8` (env) | `mc_motion/motion.py:39` |
| Gyári akciók | stand, lay_down, damp, balance, hello, stretch, `front_jump`, `front_pounce`, dance | `mc_motion/motion.py:491` |
| Gyorsabb járásmód (`SpeedLevel`, `SwitchGait`, futó gait) | **nincs bekötve**, az SDK-ban ellenőrizni kell, mit tud a mi firmware-ünk | — |
| Ugrás hossza | a `FrontJump` nem paraméterezhető, a hossza mérendő | — |

---

## 2. Ötletek — interakció a 3D térben

### 2.1 Alap: kattints és menj
1. **Cél kattintással + előnézet.** Kattintás a padlóra → a tervezett útvonal világító vonalként jelenik meg, ETA-val és a sebességprofil színezésével. Végrehajtás csak „GO” után.
2. **„Szellem-kutya” előnézet.** Áttetsző Go2 végigfut a tervezett pályán a tervezett sebességgel (idő-csúszkával). Látszik, hol lassít, hol kerül, hol ugrik.
3. **Célirány húzással.** Kattint + húz = célpozíció + a végső irány (a kutya merre nézzen a végén).
4. **Sebesség-módok gyorsbillentyűvel:**
   - normál
   - `Shift` = **SPRINT** (max sebesség)
   - `Alt` = **SETTENKEDŐ** (lassú, halk, alacsony testtartás)
   - `Ctrl` = **PRECÍZ** (lassú, pontos célba állás)

### 2.2 Útvonal-rajzolás és pályák
5. **Szabadkézi pálya.** Egérrel / ujjal rárajzolod a padlóra → spline → simítás → a robot követi; az ütközésmentességet a tervező ellenőrzi és korrigálja.
6. **Waypoint-lánc, szakaszonkénti akcióval.** Pl. `A →(sprint)→ B →(ugrás×3)→ C →(várj 5 s, 360° szkennelés)→ D →(fotó + hőkép)→ vissza`.
7. **Ismétlődő járőr.** Zárt pálya + időzítés (pl. 22:00–06:00 között 30 percenként), véletlenszerű sorrenddel, hogy kiszámíthatatlan legyen.
8. **Visszakövetés (breadcrumb).** „Menj vissza azon az úton, amin jöttél” — biztonságos visszavonulás ismert, bejárt pályán.

### 2.3 Ugrás / ugrálás
9. **„Ugrálj idáig”.** A tervező a távot `FrontJump` darabszámra bontja (a mért ugráshosszal), és minden landolási pontot ellenőriz a voxel-, illetve gridtérképen (sík, szabad, nem lépcső, nincs ember 3.5 m-en belül). Az UI-ban a landolási pontok gyűrűként látszanak.
10. **Akadály-átugrás.** Alacsony akadálynál (a `walls` réteg magassága < X cm) a tervező felajánlja az ugrást a kerülés helyett.

### 2.4 Pont- és tárgy-alapú parancsok
11. **„Nézd meg azt”.** Kattintás egy 3D-pontra a színes pontfelhőben → a robot oda fordul (test + kamera), vagy „menj oda 1.5 m-re és vizsgáld meg” (fotó + hőkép + 360° szkennelés).
12. **Szemantikus térkép.** Helyek elnevezése kattintással („kapu”, „garázs”, „töltő”); a YOLO-objektumok (autó, bicikli, ajtó) automatikusan címkézve. A parancsok ezekre hivatkozhatnak.
13. **Tiltott és figyelt zónák.** Sokszög rajzolása a padlóra: `no-go` (oda nem mehet), `watch` (ha ember lép be → riasztás), `patrol` (a határát járja).

### 2.5 Ember-központú parancsok (≥ 2.5 m, a guard felülírhatatlan)
14. **Kattintás emberre:**
    - **ÁRNYÉK** (követés 3 m-ről)
    - **FIGYELD** (helyben marad és felé fordul)
    - **KÍSÉRD** (mellette halad)
    - **ÁLLJ ELÉ 4 m-RE** (a mozgása alapján előre-pozícionálás, a távolság megtartásával)
15. **Elveszett célpont.** Az utolsó ismert pozíció + az irány alapján keresési spirál vagy frontier-keresés, a hőkamera előnyben részesítésével.
16. **Figyelmeztetés.** LED / reflektor, sziréna, előre rögzített TTS-szöveg („Ön megfigyelt területen tartózkodik.”) — a meglévő `audio` pillérrel.

### 2.6 Más bemeneti módok
17. **Gamepad (böngésző Gamepad API).** Bal kar = robot, jobb kar = kamera, ravasz = sebesség, gomb = ugrás; az előnézet itt is látszik.
18. **Természetes nyelv / hang.** „Menj a kapuhoz és nézz körül” → LLM → misszió-JSON (a 3. pont sémája) → **előnézet + jóváhagyás** → végrehajtás. Csak a sémában lévő primitíveket kaphatja, nyers sebességet nem.
19. **Gesztus.** Az ember int → a robot odajön 3 m-re; tenyér előre → STOP. (YOLO-pose kell hozzá.)
20. **Telefon / tablet.** Ugyanaz az UI érintéssel: koppintás = cél, két ujj = forgatás, hosszú nyomás = menü.

### 2.7 Autonóm viselkedések
21. **Esemény-szabályok.** Pl. „ha hőkamera embert lát a `watch` zónában éjjel” → riasztás + push értesítés + odamegy figyelni 5 m-re + felvétel indul.
22. **Visszatérés haza.** Alacsony akku, kapcsolatvesztés vagy parancs esetén → a mentett „home” pontra, a legbiztonságosabb úton.
23. **Önfeltérképezés.** „Térképezd fel ezt a sokszöget” → frontier-felfedezés a zónán belül, a végén lefedettségi riport.

---

## 3. Javasolt architektúra

### 3.1 Misszió-séma (egy nyelv: UI, gamepad, LLM, szabálymotor mind ezt állítja elő)
```json
{
  "mission_id": "m-123",
  "steps": [
    {"op": "goto", "x": 4.0, "y": 2.0, "yaw": 1.57, "speed": "sprint"},
    {"op": "follow_path", "points": [[4,2],[6,2],[6,5]], "speed": "normal"},
    {"op": "jump_to", "x": 8.0, "y": 5.0, "max_jumps": 4},
    {"op": "look_at", "x": 9.0, "y": 7.0, "z": 0.5},
    {"op": "scan", "deg": 360},
    {"op": "action", "name": "hello"},
    {"op": "wait", "s": 5},
    {"op": "shadow", "gid": 12, "dist_m": 3.0, "timeout_s": 120},
    {"op": "say", "text": "Ön megfigyelt területen tartózkodik."},
    {"op": "return_home"}
  ],
  "on_fail": "stop"
}
```
- `speed`: `stealth | precise | normal | sprint` → sebesség-, gyorsulás- és járásmód-profil a configból; **nem nyers m/s**.
- Minden lépés validálva: a térkép, a no-go zónák és a fizikai korlátok alapján, még végrehajtás előtt.

### 3.2 Komponensek
| Komponens | Hol | Feladat |
|---|---|---|
| `mission_exec` | az `orchestration` (9104) bővítése, vagy új pillér | lépések végrehajtása, állapotgép, pause/resume/abort, `mc.mission.*` események |
| `planner` | `navigation` bővítés | globális út (A* social costtal) + sebességprofil (görbület, safety, látható tér) + ugrás-landolási pontok |
| `preview` | UI | szellem-kutya szimuláció ugyanazzal a profillal |
| `safety_guard` | meglévő | változatlanul a végső kapu; a sprint és az ugrás külön engedélyt kér (lent) |

### 3.3 Biztonsági szabályok a „gyors” parancsokra
- **SPRINT** csak akkor engedélyezett, ha egyszerre teljesül:
  1. a pálya folyosójában (±1.5 m) nincs ember;
  2. a safety szint `CLEAR`;
  3. a LiDAR- és kameraadat friss;
  4. az akku > 30%;
  5. az operátor **nyomva tartja a „dead-man” gombot** (UI / gamepad). Elengedés = azonnali lassítás és megállás.
- **UGRÁS:** a landolási zóna szabad, nincs ember 3.5 m-en belül, és lépésenként jóváhagyás vagy dead-man kell. Egy hibás landolás tönkreteheti a robotot.
- A sebességplafon (`MAX_VX`) emelése **csak** sprint módban, a `safety_guard`-ban külön `sprint_vmax` paraméterrel, amit a guard a fenti feltételekhez köt.
- Az LLM által generált misszió soha nem fut jóváhagyás nélkül.

---

## 4. Javasolt sorrend

| # | Tétel | Miért ez |
|---|---|---|
| 1 | Misszió-séma + `mission_exec` (`goto`, `follow_path`, `wait`, `action`, `look_at`, `scan`) a `safety_guard`-on át | minden más erre épül |
| 2 | UI: cél kattintással, útvonal-előnézet, szellem-kutya, GO / ABORT | a fő élmény |
| 3 | `shadow` / `watch` lépés a meglévő `pursuit`-tal + UI-gomb az emberen | a követés-gomb ma nincs bekötve |
| 4 | Sebességprofilok + SPRINT dead-man-nel (előtte kutatás: `SpeedLevel` / `SwitchGait` az SDK-ban) | „fuss ide max sebességgel” |
| 5 | `jump_to` (előtte a `FrontJump` hosszának mérése) | „ugrálj idáig” |
| 6 | Szemantikus címkék + zónák + esemény-szabályok | éjszakai felügyelet |
| 7 | Természetes nyelv / hang → misszió | látványos, de jóváhagyással |
| 8 | Gamepad, gesztus, mobil UI | kényelmi funkciók |
