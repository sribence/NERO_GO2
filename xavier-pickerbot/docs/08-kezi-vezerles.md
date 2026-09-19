# Saját projekt #3 — kézi vezérlés (bázis + kar)

**Építve: 2026-09-18, robot offline (SSH nem elérhető) — semmi ebből nem lett élő roboton tesztelve.** Célja: a meglévő, csak-megfigyelő [05-sajat-projekt-iranyitopult.md](05-sajat-projekt-iranyitopult.md) irányítópult kiegészítése tényleges bázis- és kar-vezérléssel, ugyanazzal a biztonsági doktrínával, mint amit a testvér-repóban ([NERO_GO2](../) fő projekt, Go2 négylábú) a `docker/web_dashboard/joint_safety.py` + `lowcmd_sender.py` mock/real-split párra építettünk.

**FONTOS:** ez a robot **nem** a Go2 négylábú. Mecanum-alváz + 4 DOF kar, ROS1 Noetic (nem DDS/LowCmd). A Go2 ízület-számokat, sebesség-plafonokat sehol nem vettük át — minden itt szereplő szám ezen a roboton, ehhez a hajtáshoz lett (óvatosan) kitalálva, vagy explicit PLACEHOLDER-ként jelölve.

## Mi épült

| Komponens | Fájl | Állapot |
|---|---|---|
| Bázis (mecanum) Twist-építő + rate-limiter | [scripts/xavier_control/base_drive.py](../scripts/xavier_control/base_drive.py) | **valós-képes** — de csak ha valaki ténylegesen bekötné egy publish hívásba; a modul maga csak dict-eket épít |
| Kar/gripper mock sender | [scripts/xavier_control/arm_control.py](../scripts/xavier_control/arm_control.py) | **MOCK-ONLY** — szándékosan nem tud valós ROS API-t hívni |
| Webes vezérlőpult | [scripts/control_panel.html](../scripts/control_panel.html) | bázis: valós `/cmd_vel` publish, de ÉLESÍTÉS-kapu mögött, alapból KI; kar: mindig szimuláció |
| Unit tesztek | `scripts/xavier_control/tests/test_base_drive.py`, `test_arm_control.py` | 25/25 zöld (`python -m pytest tests/` a `xavier_control/` mappában) |

## Valós-képes vs. mock-only — és miért ez a különbség

**Bázis-vezérlés (`/cmd_vel`, `geometry_msgs/Twist`) valós-képesnek számít**, mert:
- Ez a Wheeltec `turn_on_wheeltec_robot` alap-driver saját, jól dokumentált konvenciója, amit a gyári `wheeltec_joy_control` package is használ.
- Egy Twist (linear.x/y, angular.z) formátumhoz nem kell ízület-szintű geometriai adat, ami hiányzik — csak sebesség-parancs.

**A kar mock-only marad** (2026-09-18 frissítés: a topic/üzenet/ízület-limit már valós, lásd lent az "Élő ellenőrzés" szakaszt — de a küldési útvonal még mindig nincs bekötve), mert:
- A gripper-érték (`arm_cmd` `data[3]`) numerikus nyitott/zárt konvenciója **nincs megerősítve** — ez az egyetlen még hiányzó darab a teljes vezérlési lánchoz.
- Egy 4 DOF karnál egy rossz gripper-érték vagy nem tesztelt sebesség/gyorsulás a gripper/bázis/tartott tárgy ütközését okozhatja — ez nem olyan kockázat, amit "óvatos becsléssel" el lehet fedezni, mint egy lassú bázis-sebességnél.
- A modul szerkezetileg (import-szint, AST-teszt) így is nem tud valós ROS API-t elérni — a valós küldés bekötése külön, tudatos következő lépés.

## A biztonsági plafonok pontos értékei és miért ilyenek

`scripts/xavier_control/base_drive.py`:

| Paraméter | Érték | Eredet |
|---|---|---|
| `MAX_LINEAR_MPS` | 0.15 m/s | **Óvatos alapérték, NEM mért hardver-plafon.** Nincs adatlap, nincs mért csúcssebesség ezen a példányon. |
| `MAX_ANGULAR_RADPS` | 0.3 rad/s | Ugyanaz — óvatos becslés, nem mérés. |
| `MAX_LINEAR_ACCEL_MPS_PER_TICK` / `MAX_ANGULAR_ACCEL_RADPS_PER_TICK` | 0.03 / 0.06 (tick ≈ 1/20 s referenciánál) | Cél: ~0.5s alatt érje el a max sebességet egy tartott gombnál, ne egy UI-kattintásra ugorjon oda azonnal. |

Ha az első élő teszten a robot gyorsabban mozog a vártnál ezekkel az értékekkel, **csökkentsd tovább** ezeket a számokat — ne emeld feljebb egy sikeres teszt után anélkül, hogy tudnád, mi a valós fizikai plafon.

`scripts/xavier_control/arm_control.py` `JOINT_LIMITS_RAD`: **2026-09-18 óta valós adat**, `mini_mec_moveit_four.urdf`-ből olvasva (`j1_joint`/`j2_joint`/`j3_joint`, mindegyik ±0.785 rad). A gripper-érték továbbra sincs kalibrálva — lásd lent az "Élő ellenőrzés" szakaszt.

## Első élő teszt — lépésről lépésre (amikor a robot legközelebb elérhető)

Ne kezdd el ezt a listát, amíg nincs valaki a robot közelében, aki fizikailag el tudja kapcsolni az áramot (tápkapcsoló/battery), és amíg nincs meg a `rostopic`-os megerősítés.

1. **SSH-kapcsolat + roscore él.** `ssh -i ~/.ssh/pickerbot_mini wheeltec@192.168.123.50`, ellenőrizd, hogy `roscore` fut (vagy indítsd el `scripts/start_feeds.sh`-val, ami már úgyis elindítja).
2. **`/cmd_vel` MEGLÉTÉNEK ellenőrzése ELŐSZÖR, mielőtt bármit küldenél:**
   ```bash
   rostopic list | grep cmd_vel
   rostopic info /cmd_vel
   ```
   Ha a topic neve vagy típusa más, mint `geometry_msgs/Twist` a `/cmd_vel` néven, **állj meg** — `base_drive.py` és `control_panel.html` mindkettő ezt a nevet/típust feltételezi, nem megerősítve. Ha eltér, előbb ezt kell javítani a kódban, nem ráerőltetni a robotra.
3. **Fizikai E-stop/kéz a tápkapcsolón.** Valaki álljon a robot mellett úgy, hogy egy mozdulattal le tudja kapcsolni az áramot (barrel jack / battery kapcsoló), mielőtt az első parancs kimegy.
4. **Nyisd meg `scripts/control_panel.html`-t** `python -m http.server 8901`-ről (ne `file://`), és ellenőrizd, hogy a `globalStatus` "rosbridge: csatlakozva"-t mutat.
5. **NE élesíts azonnal.** Előbb figyeld pár másodpercig a naplót MOCK módban (élesítés nélkül) — minden gombnyomás "MOCK (nincs élesítve)" sort ír, ellenőrizd, hogy az irányok logikusak (előre=x+, balra strafe=y+, stb.), mielőtt bármi kimenne a robotra.
6. **Élesítés minimális sebességgel.** Kattints az ÉLESÍTÉS gombra (megerősítő dialógus jön), majd **rövid, kis nyomásokkal** próbáld ki egyenként az irányokat — ne tartsd lenyomva hosszan az első próbánál.
7. **E-STOP gomb / szóköz-billentyű reflex.** Az E-stop gomb azonnal nulla Twist-et küld és leélesít — próbáld ki ezt is tudatosan, mielőtt bármilyen komolyabb mozgást kérnél.
8. **Karvezérlés valós bekapcsolása NEM ezen a listán van.** A kar addig marad szimuláció-only, amíg valaki nem olvassa le a valós ízület-határokat a `mini_mec_four_arm_moveit_config`-ból (vagy élő `rosparam`/`rostopic`/`rosservice` hívásokkal a running MoveIt node-okról), és be nem írja azokat `arm_control.py`-ba a `PLACEHOLDER` jelölés törlésével együtt — külön, tudatos lépésként, nem ennek a dokumentumnak a részeként.

## Amit ez a projekt NEM csinál

- Nem hívja soha az `/camera/toggle_ir` service-t — lásd [07-ismert-hibak.md](07-ismert-hibak.md).
- Nem tesz semmilyen feltételezést a robotkar valós topic-nevéről, üzenettípusáról vagy ízület-sorrendjéről — minden ilyen `arm_control.py`-ban PLACEHOLDER-ként van jelölve.
- Nem indít semmilyen SSH-kapcsolatot magától a robot felé (ezt a session sem tette, mert a robot offline volt).

## Élő ellenőrzés — 2026-09-18, második session (robot elérhető, földön)

A robot ekkor fizikailag a földön volt (nem asztalon — leszedve előtte, hogy egy véletlen `/cmd_vel` ne tudja leejteni), SSH élt (`192.168.123.50`, lásd [09-robot-halozat.md](09-robot-halozat.md)). **Csak olvasó jellegű ellenőrzés történt: roscore + bázis-bringup elindítva, `rostopic`/forráskód-vizsgálat, majd minden folyamat leállítva. Egyetlen mozgás- vagy kar-parancs sem lett élesben elküldve.**

Indított bringup: `roslaunch turn_on_wheeltec_robot turn_on_wheeltec_robot.launch car_mode:=mini_mec_moveit_four` (a `car_mode` értéke a 07-ismert-hibak.md `tf_echo`-javításából volt már ismert). Utána minden ROS-folyamat (`roscore`, `rosmaster`, `rosout`, `wheeltec_robot_node`) leállítva `pkill`-lel — a robot most idle állapotban van.

**Megerősítve:**
- `/cmd_vel` **valós**, `geometry_msgs/Twist`, feliratkozó: `/wheeltec_robot` node. `base_drive.py` és `control_panel.html` feltételezése helyes volt.
- `/arm_cmd` is **valós** (eddig ismeretlen volt) — `std_msgs/Float32MultiArray`, ugyanaz a `/wheeltec_robot` node fogadja (nincs külön MoveIt action-szerver). `wheeltec_robot.cpp` `joint_states_Callback`-jából leolvasva: `data = [j1_rad, j2_rad, j3_rad, gripper_raw]`. A három szög radiánban megy, a firmware-híd ×1000-rel skálázva int16-ba csomagolja — a hívónak radiánt kell adnia. A `gripper_raw` közvetlenül `uint8_t`-re van castolva, skálázás nélkül — **a nyitott/zárt pontos numerikus konvenciója továbbra sincs megerősítve** (a repóban sehol máshol nincs másik `/arm_cmd` publisher, amiből ki lehetne olvasni).
- Valós ízület-nevek/határok a robot `mini_mec_moveit_four.urdf`-jéből (`turn_on_wheeltec_robot/urdf/`): `j1_joint`, `j2_joint`, `j3_joint` — mindegyik `type="revolute"`, `lower="-0.785" upper="0.785"` (±45°), `effort="100"` (egység nem világos, valószínűleg generikus MoveIt-exportőr alapérték, nem mért adat), `velocity="0"` (nincs megadva — **nem** "korlátlan", ebből sebesség-plafont nem lehet levezetni). A `/joint_states`-ben látott `j4_1_joint..j4_6_joint` egy mechanikusan összekötött gripper-ujj szerelvény, nem külön vezérelhető — az `/arm_cmd` egyetlen `gripper_raw` értéke mozgatja mindet együtt.
- **`arm_control.py` frissítve valós adattal:** `PLACEHOLDER_JOINT_LIMITS_RAD` → `JOINT_LIMITS_RAD`, 4 kitalált érték helyett a 3 valós URDF-limit (±0.785 rad mindhárom ízületre). A modul **továbbra is mock-only** — a gripper-konvenció és a valós mozgás-viselkedés (sebesség/gyorsulás) még nincs megerősítve, ezért a valós küldési útvonal szándékosan nincs bekötve. 25/25 teszt zöld mindkét klónban (`C:\dev\NERO_GO2\xavier-pickerbot\` és `C:\Users\user\NERO_GO2\xavier-pickerbot\`) a frissítés után.

**Még nyitva marad — kar valós küldés előtt ez kell:**
1. `gripper_raw` numerikus konvenciójának tisztázása (pl. egy manuális, kis értékű teszt-küldés közvetlen `rostopic pub`-bal, valaki a gripper mellett figyel, NEM ezen a modulon át).
2. Valós sebesség/gyorsulás-viselkedés megfigyelése kis, felügyelt mozdulatokkal, mielőtt bármilyen automatizált küldő épülne rá.
3. Utána — külön, tudatos lépésként — egy valós `ArmSender` építése a `lowcmd_sender.py`/`base_drive.py` mintájára, ARMED-gate mögött.

## Nyitott kérdés (bázis) — LEZÁRVA 2026-09-18

`/cmd_vel` léte/típusa most már élőben megerősítve (lásd fent) — a bázis-vezérlés `control_panel.html`-ben biztonságosan élesíthető, a dokumentált Első élő teszt eljárással (minimum sebesség, E-stop kéznél).

## Fizikai incidens — 2026-09-18, harmadik session (LAN-port tönkrement)

Bázis-vezérlés élő tesztje közben (webes UI, ÉLESÍTVE) a robot egyik kereke befogta/feltekerte a beépített LAN-portba kötött Ethernet-kábelt. A szoftveres E-STOP gomb (`hardStop()` + `setArmed(false)`, zero Twist publish) **nem állította meg időben a mozgást** — a kábel kitépődött, a beépített LAN-csatlakozó pin-jei eltörtek, a beépített port használhatatlanná vált.

**Következmény/workaround:** a robotra USB-LAN adapter került, ami új interfészt hoz létre (`eth0`, a régi beépített port most `eth1`, `NO-CARRIER`). A meglévő statikus NetworkManager-profil (`192.168.123.50/24`) átvette az új interfészt automatikusan újracsatlakozáskor — külön beavatkozás nem kellett, de ezt validálni kell minden újracsatlakozáskor (`ip a` — melyik interfész van `UP`+`LOWER_UP` állapotban `.50`-es címmel).

**Nyitott biztonsági kérdés, még nincs kivizsgálva:** miért nem állította meg az E-STOP a mozgást időben? Lehetséges okok, egyik sincs megerősítve:
- a `/cmd_vel` publish késleltetve/nem érkezett meg időben a 100ms-es tick-loop és a rosbridge WebSocket felett,
- a mozgás nem is szoftveres `/cmd_vel` parancsból jött ebben a pillanatban, hanem a kábel fizikai feszülése/tekeredése hajtotta tovább a kereket a motor kikapcsolása után is (mechanikai tehetetlenség/behúzás, nem elektronikus hiba),
- vagy a `/wheeltec_robot` node maga nem reagált elég gyorsan egy zero-Twist üzenetre.
Amíg ez nincs tisztázva: **kábelt/laza tárgyat sose hagyj a kerekek közelében élő teszt közben**, és a fizikai E-stop-hoz/tápkapcsolóhoz való hozzáférés (kéz a közelben) kötelező marad minden bázis-teszthez, nem csak a szoftveres gomb.

## Élő ellenőrzés — 2026-09-18, harmadik session (kar, első valódi `/arm_cmd` küldések, felügyelt)

A LAN-javítás után a robot egy stabil, nem-eshető/nem-elgurulható platformon volt rögzítve. Bázis-bringup (`turn_on_wheeltec_robot.launch`) és `rosbridge_websocket` újraindítva (egyik se élt a fizikai incidens/reboot óta). `/wheeltec_robot` node egészséges, `/PowerVoltage` ~21.9V (stabil, nem lemerülés-jel).

**Első valódi `/arm_cmd` küldések ezen a roboton, kézi `rostopic pub -1`-lel, felügyelve (a user fizikailag figyelte a kart):**
- `[0,0,0,0]` — nem történt látható mozgás. **Magyarázat a forráskódból** (`wheeltec_robot.cpp:91-99`): a node csak akkor küld tovább adatot a soros vonalra, ha az új érték >0.01-dal eltér az utolsó elküldött (`last_A/B/C/last_grap`) értéktől — ha ez egyezett a defaulttal, a parancs valószínűleg el sem jutott a szervókig, nem azért nem mozdult semmi, mert már ott volt.
- `[0.15, 0.0, 0.0, 0.0]` (j1 ≈ 8.6°) — elindult, majd **"kiakadt"**: mozgás közben leállt, utána a visszahívás (`[0,0,0,0]`) **sem** mozdította vissza. Feltételezett ok: a szervó saját túlterhelés-/blokkolásvédelme (a driver forráskódja bizonyítottan **sosem** kér vissza pozíciót/hibaállapotot a boardtól — `wheeltec_robot.cpp` csak küld, sosem olvas —, ez a viselkedés a szervó/board saját, ROS-ból láthatatlan szintjén dől el).
- Kb. 1-2 perccel később, power-cycle **nélkül**: `[0.05, 0.0, 0.0, 0.0]` — **ment**, kis mértékben mozdult. A "kiakadás" tehát önmagától old idővel (időzített túlterhelés-timeout jellegű viselkedés), nem szorul fizikai power-cycle-ra.
- `[0.15, 0.0, 0.0, 0.0]` újra (visszatérve a korábban kiakadáshoz vezető célértékhez) — **megint kiakadt**. Vissza `[0.05, 0.0, 0.0, 0.0]`-ra — ment, stabilan ott hagyva a kart.

**Következtetés:** j1 megbízhatóan, mozgás nélküli kiakadás nélkül tesztelve `0`–`0.05` rad tartományban. `0.15` rad körül (a ±0.785 rad URDF-limiten belül, tehát nem szoftveres limit-ütközés) **kétszer is** kiakadt, egyszer viszont (a legelső próbálkozás, más előzmény-állapotból) simán elment volna — ez arra utal, hogy nem egy tiszta, konzisztens mechanikai végállás, hanem valami **időszakos fizikai akadály vagy súrlódás** j1 mozgási útjában valahol 0.05–0.15 rad között. **Mielőtt tovább tesztelnénk j1-et ebben a tartományban: fizikailag át kell nézni, nincs-e kábel/tárgy/mechanikai interferencia a kar forgási útjában.** j2/j3 és a gripper (`data[3]`) még egyáltalán nincs élőben tesztelve.

STM32 board saját natív soros protokollja (ami elvben tudhat Home/torque-enable/hiba-törlés parancsot) **nincs dokumentálva és nincs forráskódja ezen a Jetsonon** — csak a szűk, egyirányú ROS-driver protokoll ismert (`wheeltec_robot.cpp`). Vendor upper-computer/firmware-forrás keresése (ha van ilyen) külön feladat, ha a jövőben mélyebb hozzáférés kell a board-hoz.

**Gyökér-ok azonosítva: lemerült akku.** STM32 board manuális reset után `/PowerVoltage` **17.74V**-ra esett (korábban ~21.9-22.5V stabil volt ugyanabban a sessionben). Ezzel egy időben j2/j3 szervó **teljesen elengedte magát** (kézzel szabadon forgatható, nulla tartónyomaték), miközben j1 még tartotta magát. Ez valószínűleg megmagyarázza a korábbi j1 "kiakadásokat" is (0.15 rad körül, határeset viselkedés) — alacsony feszültségnél a szervók sorban veszítik el a working marginjukat, j1 bírta tovább, j2/j3 már nem. **Interaktív jog-teszt (`arm_jog.py`) eddig csak j1-en lett érdemben kipróbálva** (q/a billentyűk) — j2/j3 (w/s, e/d) tesztje az akku-lemerülés miatt félbeszakadt, folytatás töltés után szükséges. Robot most töltőn.

## Automatikus indítás (systemd) — 2026-09-18

Kolléga-teszteléshez a robot mindent magától elindít bekapcsoláskor: `pickerbot-bringup` (bázis-driver) → `pickerbot-rosbridge` (9090, függ a bringup-tól) → `pickerbot-webui` (8901-es `http.server`, `/home/wheeltec/pickerbot_web_ui/`). Unit fájlok: `/etc/systemd/system/pickerbot-*.service` a roboton (nincsenek ebben a repóban verziózva, csak a roboton élnek). Mind `enable`-ölve, `Restart=on-failure`. Kolléga csak a robot-hálóra csatlakozik, és megnyitja `http://192.168.123.50:8901/control_panel.html`-t — SSH nem kell.

## Kézi jog-eszköz kar-teszthez

[`/home/wheeltec/arm_jog.py`](robot, nincs repóban) — interaktív terminál-script, `rospy` + nyers billentyű-olvasás (`termios`/`tty`), csak j1/j2/j3-at mozgatja, gripper (`data[3]`) mindig `0.0`. Billentyűk: `q`/`a` = j1 +/-, `w`/`s` = j2 +/-, `e`/`d` = j3 +/-, `+`/`-` = lépésköz (alap 0.02 rad), `x` = kilépés. Induló pozíció `[0.05, 0.0, 0.0]` (utolsó ismert biztonságos j1-érték ebből a sessionből).

Futtatás (Windows terminálból, `-t` kötelező a pty-allokációhoz):
```
ssh -t -i ~/.ssh/pickerbot_mini wheeltec@192.168.123.50 "source /opt/ros/noetic/setup.bash; python3 /home/wheeltec/arm_jog.py"
```
