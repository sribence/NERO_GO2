# Saját projekt #2 — Pickerbot Akadémia

## A vízió

Egyetemisták számára készülő, távolról elérhető oktatási robotika-platform. Nem raw ROS-node-írás, és nem is egyszerű joystickes játék — egy **tíz szintes, lépcsőzetes tananyag**, ahol a diákok előre megírt "képesség-modulokat" hangolnak, mérnek és kalibrálnak, miközben nézik, ahogy a robot reagál:

1. Mecanum kerék-kinematika kalibrálás
2. Odometria-kalibrálás (LiDAR fal-távolság kereszt-ellenőrzéssel)
3. Absztrakt útvonalpont-vezérlés
4. 2D LiDAR térkép-illesztés (scan matching)
5. Valódi SLAM + navigáció
6. Klasszikus látás (vonalkövetés, jelfelismerés)
7. Objektumdetektálás
8. Szemantikus navigáció (szín/objektum-alapú megközelítés)
9. 3D mélységérzékelés + kar-geometria (grasping)
10. Teljes küldetés — az összes réteg összekapcsolva

A teljes, 11 architektúra-ábrás terv: [pickerbot-akademia-terv.html](../pickerbot-akademia-terv.html).

## Architektúra dióhéjban

Négy réteg: **Böngésző ↔ Gateway** (auth, sor, konfig-tár, futás-archívum, szimulátor-instance-ok) **↔ Robot Agent** (fedélzeti ügynök: szűk, whitelistelt parancs-API, biztonsági felügyelő, paraméter-kezelő, telemetria) **↔ ROS-stack**. Az Agent mindig kifelé hív a Gateway-hez (nem kell bejövő port-forward), ez teszi lehetővé, hogy a Gateway ROS-verzió-független maradjon, ahogy a flotta bővül ROS1-ről (ez a Jetson) ROS2-re (jövőbeli Raspberry Pi-alapú robotok).

Minden tananyag-szint egyetlen, séma-konform **"skill manifest"** (YAML) alapján generálja mind a frontend vezérlőit, mind a robotoldali ROS-paraméter/teszt bekötést — új, tizenegyedik skill hozzáadása így nulla frontend-kódváltoztatást igényel.

## Az autonóm generáló pipeline ("academy-forge")

Mivel a robot fizikailag nem volt jelen a tervezés alatt, minden olyan projektrész, ami a robot nélkül generálható (sémák, tananyag-szövegek, gateway/frontend kód, robot-oldali Python-modulok, szimulátor-leírók), **helyi Qwen3/Qwen2.5-Coder modellel generálódik**, a `main` GPU-gépen (2× RTX 5070), nem kézzel.

Struktúra:

- `brain/` — kontextus-dokumentumok (vízió, hardver-leltár, architektúra, tananyag, konvenciók, **nyitott kérdések lista** — kritikus, hogy a modell ne találjon ki hardveradatot)
- `agents/` — 7 szerepkör system promptja (architect, reviewer, ros_engineer, backend_engineer, frontend_engineer, curriculum_designer, sim_engineer), modellenként/hőmérsékletenként hangolva
- `tasks/` — 40 feladatos deklaratív backlog, függőségekkel és elfogadási kritériumokkal
- `forge/run.py` — a loop-motor: generál → validál (szintaxis + projektszabályok) → adversarial reviewer (külön modell-hívás) → hiba esetén javító kör (max 4 próba) → csak akkor `done`, ha átment

A pipeline forráskódja jelenleg a fejlesztőgépen és a `main` gépen (`~/pickerbot-academy/`) él — ebbe a repóba (egyelőre) nem került át, mert még aktívan fut és iterál.

## Státusz

A generálás folyamatban van. Eddigi tanulság: a rendszer megbízhatóan generál YAML tananyag-manifeszteket és Python-kódot (1-2 próbából), de rendszeresen elakadt egy szűk, azonosított mintázaton — JSON Schema-ban és TypeScript-ben "zárt kulcs-szótár", "cross-field alapérték" és "változó típusú mező" modellezése. A javítás: a helyes minták explicit, kód-példás bekötése az agent-promptokba, nem a modell "kitalálja magától" hozzáállás. Ez működött — az érintett feladatok a javítás után 1-2 próbából átmentek, ahol előtte mind a 4-et kimerítették.
