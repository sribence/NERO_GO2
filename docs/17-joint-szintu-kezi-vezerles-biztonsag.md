# Joint-szintű (LowCmd) kézi vezérlés — biztonsági réteg

**Státusz (2026-09-17 este): safety-modul + LowCmdSender (mock-only) +
unit tesztek készek, valódi robotra még sosem küldött parancsot. Ez a
dokumentum a holnap reggeli első robotos teszthez készült checklist is —
ld. alul "Robotos teszt eljárás", és a mock LowCmd-építésről a lenti
"LowCmdSender (mock-only, 2026-09-17 este)" szekciót.**

Kapcsolódó TODO-elem: [12-taszklista.md](12-taszklista.md) / `TODO.md`
"Robot csuklóinak (hip/thigh/calf) külön-külön, kézi vezérlése".

## Mi készült el

- [`docker/web_dashboard/joint_safety.py`](../docker/web_dashboard/joint_safety.py)
  — `JointSafetyManager` osztály.
- [`docker/web_dashboard/tests/test_joint_safety.py`](../docker/web_dashboard/tests/test_joint_safety.py)
  — 13 unit teszt, mind zöld (`python -m pytest tests/test_joint_safety.py -q`).

## Mi HIÁNYZIK még (nem áltatjuk magunkat)

- **Nincs LowCmd küldő útvonal.** `app.py` jelenleg kizárólag a gyári
  `SportClient` magas szintű hívásait használja (`Move`, `RecoveryStand`,
  `StandDown`, `Hello`, `Heart`, `Sit`) — nincs sehol `LowCmd`/`LowState`
  publish/subscribe. A `JointSafetyManager` egy előre megépített védőréteg
  egy még nem létező vezérlési útvonalhoz.
- **Nincs operátori UI-panel** kézi csukló-vezérléshez (a meglévő joystick
  csak a `SportClient.Move()`-ot hajtja).
- **Nincs watchdog-integráció** a joint-szintű útvonalra (a P0
  watchdog/E-stop réteg csak a fő `SportClient` mozgásra létezik,
  ld. `mission-control/tests/test_watchdog.py`).
- Emiatt a holnapi teszt **nem** élő joint-vezérlés lesz, csak a safety
  matek önálló validálása (ld. lentebb).

## A JointSafetyManager API

```python
from joint_safety import JointSafetyManager

safety = JointSafetyManager()  # 5° margin, 3°/tick rate limit, kp≤60, kd≤5

# Egy hívás, LowCmd-re kész dict-et ad vissza:
cmd = safety.clamp_full(target_q, current_q, kp=20.0, kd=1.0, tau=None)
# cmd = {"q": [...], "kp": [...], "kd": [...], "tau": [...]}
```

Négy réteg, sorban:

1. **`clamp_rate(target_q, current_q)`** — max 3°/tick elmozdulás, hogy egy
   rossz UI-érték vagy joystick-ugrás ne rántsa a lábat hirtelen nagyot.
2. **`clamp_position(q)`** — URDF (`go2_description.urdf`) szöghatárok, 5°
   biztonsági ráhagyással mindkét oldalon. Első/hátsó thigh-limit eltér,
   ezt a modul lábanként külön kezeli.
3. **`clamp_gains(kp, kd)`** — stiffness/damping felső korlát (kp≤60,
   kd≤5), hogy manuális módban ne lehessen a gyári trot-gait-nél
   keményebb rugóval "belőni" egy ízületet.
4. **`clamp_torque(tau)`** — feedforward nyomaték URDF effort-limitre
   kapcsolva (hip/thigh 23.7 Nm, calf 45.43 Nm).

Külön hívható metódusok is: `clamp_position`, `clamp_rate`, `clamp_gains`,
`clamp_torque`, `is_safe(q)`, `limits_for(joint_index)`.

## Robotos teszt eljárás (holnap reggel)

Safety-kritikus — ld. [00-BIZTONSAGI-SZABALYOK.md](00-BIZTONSAGI-SZABALYOK.md).
**A robotnak NEM küldünk élő joint-parancsot, amíg a lenti 1-4. pont nem zöld.**

1. **Unit teszt frissen, robot nélkül:**
   ```bash
   cd docker/web_dashboard
   python -m pytest tests/test_joint_safety.py -q
   ```
   Várt: `13 passed`. Ha nem — **állj meg itt**, ne menj tovább robotra.

2. **Határeset-szimuláció, még robot nélkül** — nyisd meg Python REPL-ben:
   ```python
   from joint_safety import JointSafetyManager
   safety = JointSafetyManager()
   # 1) Nyugalmi állás pózra nulla korrekciót ad?
   stand = [0.0, 0.8, -1.5] * 4
   assert safety.clamp_position(stand) == stand
   # 2) Extrém/hibás bemenetre tényleg URDF-en belül marad?
   print(safety.clamp_full([9.0]*12, stand))
   ```
   Nézd át kézzel a kiírt `q` értékeket — minden hip/thigh/calf a
   `limits_for(i)` tartományban legyen.

3. **Robot bekapcsolása, DE csak SportClient módban marad** (jelenlegi
   `app.py` útvonal) — a mai napon **nincs** joint-szintű élő parancs,
   csak azt ellenőrizzük, hogy a meglévő magas szintű vezérlés (Állás,
   Séta, Ülés stb.) változatlanul jó, a safety-modul commitja nem törte el
   véletlenül `app.py`-t:
   ```bash
   python -m pytest docker/web_dashboard -q   # ha van teljes tesztfájl-kör
   ```

4. **Vészleállító kéznél legyen** (fizikai E-stop / a robot saját gombja)
   mielőtt bármi mozgó tesztet futtatsz — még SportClient szinten is.

5. **Csak ha 1-4 zöld:** döntsd el, hogy a LowCmd küldő útvonal megépítése
   (jelenleg hiányzik, ld. fent) a következő lépés, vagy marad a mai nap
   a safety-matek validálásánál. Élő `LowCmd` publish **NE** menjen a
   robotra addig, amíg nincs hozzá watchdog + operátori UI is (ld. TODO).

## Ismert nyitott kérdés

`unitree_sdk2py` `LowCmd`/`LowState` API pontos mezőnevei (`q`, `dq`, `tau`,
`kp`, `kd` motor_cmd-onként) még nincs kódból megerősítve ebben a repóban —
csak a `LowState_` olvasó oldal van ellenőrizve (`app.py` `_init_sdk()`,
2026-09-01-es kommentje szerint a hivatalos `unitree_sdk2_python` forrás
ellen ellenőrizve). A `LowCmd` **írás** oldal API-ját a LowCmd küldő
útvonal megépítésekor kell ugyanígy forrásból ellenőrizni, nem kitalálni.

**Frissítés (2026-09-17 este): a `LowCmd` írás oldal mezőnevei mostanra
forrásból ellenőrizve — ld. lentebb "LowCmdSender (mock-only)" szekció.**

## LowCmdSender (mock-only, 2026-09-17 este)

**Ez a szekció CSAK a mai esti mock-tesztelést dokumentálja. Élő robotra
LowCmd publish útvonal MA ESTE SEM lett megépítve — ld. lent "Mi továbbra
is hiányzik".**

### Mi készült el

- [`docker/web_dashboard/lowcmd_sender.py`](../docker/web_dashboard/lowcmd_sender.py)
  — `LowCmdSender` osztály. A meglévő `JointSafetyManager`-re épül, nem
  duplikálja a klemmelő logikát: minden `send()`/`build_command()` hívás
  első lépése `self.safety.clamp_full(...)`.
- [`docker/web_dashboard/tests/test_lowcmd_sender.py`](../docker/web_dashboard/tests/test_lowcmd_sender.py)
  — 9 unit teszt, mind zöld:
  ```bash
  cd docker/web_dashboard
  python -m pytest tests/test_lowcmd_sender.py tests/test_joint_safety.py -q
  ```
  Eredmény: **22 passed** (9 új + a meglévő 13, változatlanul). A teljes
  `docker/web_dashboard` teszt-kör is lefutott: **33 passed**, tehát a
  `joint_safety.py` és `app.py` viselkedése nem sérült.

### API

```python
from joint_safety import JointSafetyManager
from lowcmd_sender import LowCmdSender

safety = JointSafetyManager()
sender = LowCmdSender(safety)  # tick_interval_s=0.002 (500Hz) az alapérték

# build_command(): csak megépíti a klemmelt parancsot, nem rögzíti
cmd = sender.build_command(target_q, current_q, kp=20.0, kd=1.0, tau=None)

# send(): build_command() + rögzítés self.sent listába (mock — nincs valós küldés)
cmd = sender.send(target_q, current_q, kp=20.0, kd=1.0, tau=None)
sender.sent  # [{"head": (0xFE, 0xEF), "level_flag": 0xFF, "gpio": 0, "motor_cmd": [...]}]
```

A `LowCmdSender`-nek **nincs olyan publikus metódusa**, amely megkerülné a
`clamp_full()` hívást — ezt a `test_lowcmdsender_has_no_send_method_that_bypasses_the_safety_clamp`
teszt ellenőrzi (a publikus metódusok halmaza pontosan `{build_command, send}`).

### Melyik valós Unitree `LowCmd_` mezőnév van forrásból ellenőrizve

Forrás: [`unitree_sdk2py` GitHub, `master`](https://github.com/unitreerobotics/unitree_sdk2_python),
`example/go2/low_level/go2_stand_example.py` + `unitree_legged_const.py`,
2026-09-17-én lekérve.

**Ellenőrizve (valós SDK-ból, nem kitalálva):**

- `unitree_go_msg_dds__LowCmd_()` — a `LowCmd_` üzenet gyári konstruktora
  (`unitree_sdk2py.idl.default`-ból).
- `low_cmd.head[0] = 0xFE`, `low_cmd.head[1] = 0xEF`
- `low_cmd.level_flag = 0xFF` (= `LOWLEVEL` konstans `unitree_legged_const.py`-ban)
- `low_cmd.gpio = 0`
- `low_cmd.motor_cmd[i]` — 20 elemű tömb (Go2 lábakhoz csak 0-11 index használt),
  minden elemen: `.mode` (`0x01` = PMSM mód), `.q`, `.dq`, `.kp`, `.kd`, `.tau`
- `low_cmd.crc = CRC().Crc(low_cmd)` — közvetlenül publish előtt számolva
  (`unitree_sdk2py.utils.crc.CRC`)
- Publish: `ChannelPublisher("rt/lowcmd", LowCmd_)` majd `.Write(low_cmd)`
- **Control-loop ráta: `RecurrentThread(interval=0.002, ...)` = 500Hz / 2ms**
  — ez a `lowcmd_sender.py`-beli `_MIN_TICK_INTERVAL_S = 0.002` forrása,
  nem kitalált szám.

**NEM ellenőrizve / placeholder marad:**

- A `dq` pontos szemantikája kézi (nem szkriptelt) pozíció+feedforward-tau
  parancsnál — a hivatalos példa csak `dq = 0` értéket használ saját
  szkriptelt felállás-mozgása alatt, sosem a `VelStopF` (16000.0) sentinel
  értéket. `lowcmd_sender.py` ezt a `dq=0.0` konvenciót másolja, de ez
  **nincs** megerősítve Unitree saját alacsony-szintű vezérlési
  dokumentációjából — csak az egyetlen elérhető példakódból következtetve.
- A `crc` mező kiszámítási módja ellenőrizve van (`CRC().Crc(...)`), de
  a `LowCmdSender` mock parancsdict-je **szándékosan nem tartalmaz `crc`
  kulcsot** (ld. `test_build_command_has_no_crc_field_since_nothing_is_published`),
  mert ez a dict sosem megy publish-ra — nem akarunk hamis/kitöltött `crc`
  értéket, amit valaki véletlenül élesnek hihetne.
- A `PosStopF` (2.146e9) és `VelStopF` (16000.0) sentinel-értékek pontos
  felhasználási szabálya (mikor kell "hold current position" jelzésre
  használni) nincs ellenőrizve, és a `LowCmdSender` nem is használja őket.

### Mi továbbra is hiányzik (élő robothoz)

- **Nincs valós DDS publish oldal.** `lowcmd_sender.py` szándékosan NEM
  importál `unitree_sdk2py`-t, nem hoz létre `ChannelPublisher`-t, nem hív
  `ChannelFactoryInitialize`-t — ezt kódszinten a
  `test_module_never_imports_unitree_sdk2py_or_dds` teszt bizonyítja
  (AST-elemzéssel, nem csak substring-kereséssel a docstring miatt).
  Ez a hiány **szándékos**, nem elfelejtett lépés.
- `app.py` startup-ja **nem** importálja/indítja a `LowCmdSender`-t —
  a modul teljesen leválasztva él, csak a teszt futtatja.
- Watchdog-integráció ehhez az útvonalhoz továbbra sincs (ld. TODO.md
  "watchdog-integráció ehhez az útvonalhoz" pont — változatlanul nyitott).
- Operátori UI-panel változatlanul nincs.
- Ha legközelebb valós publish épül: a fenti "NEM ellenőrizve" pontokat
  (elsősorban a `dq` szemantikát) Unitree saját alacsony-szintű
  dokumentációjából (nem csak egy szkriptelt demóból) kell megerősíteni,
  mielőtt éles robotra megy bármi.
