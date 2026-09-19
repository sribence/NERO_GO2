# Xavier Pickerbot Mini

**Wheeltec gyártmányú, "Xavier Pickerbot Mini" néven értékesített oktatási robot** — mecanum kerekes alváz + 4 tengelyű robotkar, NVIDIA Jetson Xavier NX fedélzeti számítógéppel, LiDAR-ral és Orbbec Astra RGBD mélységkamerával.

Ez az alprojekt a [NERO_GO2](../) repó testvér-dokumentációja: amíg a fő repó a Unitree Go2 négylábút dolgozza fel, ez a mappa ugyanazt csinálja a másik robotunkkal, a Xavierrel. Két külön gép, két külön hardver, közös cél: nyílt, magyar nyelvű tudásbázis a Neumann Robotics robotjairól, mielőtt bárki hozzányúlna.

## Tartalomjegyzék

- [docs/00-hozzaferes.md](docs/00-hozzaferes.md) — hálózat, SSH, hogyan köss rá egy laptopot
- [docs/01-hogyan-elesztettuk-fel.md](docs/01-hogyan-elesztettuk-fel.md) — a robot állapota első bekapcsoláskor, és milyen hibákon vittük át élő állapotba
- [docs/02-hardver-es-rendszer.md](docs/02-hardver-es-rendszer.md) — Jetson platform, OS, ROS, lemezállapot
- [docs/03-erzekelok-aktuatorok.md](docs/03-erzekelok-aktuatorok.md) — kamerák, LiDAR, kar — topicok, mért adatok, driver-korlátok
- [docs/04-gyari-szoftver.md](docs/04-gyari-szoftver.md) — mi van a lemezen gyárilag, mit használunk belőle és mit nem
- [docs/05-sajat-projekt-iranyitopult.md](docs/05-sajat-projekt-iranyitopult.md) — **saját projekt #1**: élő webes irányítópult (kamerák + LiDAR + 3D point cloud)
- [docs/06-sajat-projekt-akademia.md](docs/06-sajat-projekt-akademia.md) — **saját projekt #2**: Pickerbot Akadémia — oktatási robotika-platform terve + autonóm generáló pipeline
- [docs/07-ismert-hibak.md](docs/07-ismert-hibak.md) — hibajelenség → ok → javítás táblázat, drágán megszerzett tudás
- [docs/08-kezi-vezerles.md](docs/08-kezi-vezerles.md) — **saját projekt #3**: kézi vezérlés (bázis-drive valós-képes ÉLESÍTÉS mögött, kar MOCK-ONLY) — 🔴 élő teszt előtt olvasd el, `/cmd_vel` nincs megerősítve ezen a robotpéldányon
- [docs/09-robot-halozat.md](docs/09-robot-halozat.md) — **a közös robot-hálózat** (2026-09-18): gateway PC + TP-Link router, IP-kiosztás, elérés, hibaelhárítás
- [scripts/](scripts/) — a ténylegesen használt kapcsolódó/indító szkriptek, másolható egy az egyben
- [inventory.html](inventory.html) — vizuális szoftver-/tárhely-leltár a robot lemezéről
- [pickerbot-akademia-terv.html](pickerbot-akademia-terv.html) — a teljes Akadémia-terv, 11 architektúra-ábrával

## Gyors infó

| | |
|---|---|
| Modell | Wheeltec "Xavier Pickerbot Mini" (mecanum alváz + 4 DOF kar) |
| Fedélzeti gép | NVIDIA Jetson Xavier NX, JetPack/L4T 35.6.1 |
| OS | Ubuntu 20.04.6 LTS |
| ROS | Noetic (ROS 1, catkin), Python 3.8.10, CUDA 11.4 |
| IP | `192.168.123.50` (fix, a közös robot-hálón — lásd [docs/09-robot-halozat.md](docs/09-robot-halozat.md)); a saját Wi-Fi hotspotján továbbra is `192.168.0.100` |
| SSH | kulcsos, jelszó nélkül — `wheeltec@192.168.123.50`, kulcs: `~/.ssh/pickerbot_mini` |
| Sudo jelszó | `dongguan` (gyári alapértelmezett — ugyanaz, mint a Wi-Fi hotspot jelszava) |
| Státusz | élő, tesztelt irányítópult 2026-08-25 óta; kézi vezérlés élőben megerősítve 2026-09-18; oktatási platform terve kész, generálása folyamatban |
| Webes vezérlőpult (LAN-on bárkinek) | `http://192.168.123.50:8901/control_panel.html` — **automatikusan indul bekapcsoláskor** (systemd, lásd lent), a robot-hálóra (Wi-Fi vagy kábel, lásd [docs/09-robot-halozat.md](docs/09-robot-halozat.md)) csatlakozó bármelyik géppel elérhető, nem kell SSH vagy kézi indítás |

## Kolléga-teszteléshez: mindent automatikusan indít a robot

**2026-09-18 óta:** a robot bekapcsolásakor/reboot után magától elindul minden, ami a webes vezérlőpulthoz kell — SSH és kézi parancs NEM szükséges. Csak csatlakozni kell a robot-hálóra (lásd [docs/09-robot-halozat.md](docs/09-robot-halozat.md): Wi-Fi AP vagy kábel a gateway PC-n át), és megnyitni: `http://192.168.123.50:8901/control_panel.html`.

Roboton futó systemd service-ek (`sudo systemctl status <név>` az ellenőrzéshez):
- `pickerbot-bringup` — `turn_on_wheeltec_robot.launch` (bázis-driver, `/cmd_vel`, `/arm_cmd`, `/odom`, `/imu`, `/PowerVoltage`)
- `pickerbot-rosbridge` — `rosbridge_websocket` (9090-es port, ettől függ a bringup-tól)
- `pickerbot-webui` — a `pickerbot_web_ui/` mappát szolgálja ki 8901-en (`control_panel.html`, `dashboard.html`)

Mindhárom `enable`-ölve van, `Restart=on-failure`-ral — összeomlás után maguktól újraindulnak.

## ⚠️ Mielőtt hozzányúlnál

- **USB-C a Jetsonon adatport, nem tápbemenet.** Csak a barrel jack (19V) vagy a robot saját akkuja indítja el.
- **Az `/camera/toggle_ir` service hívása összeomlasztja a kameradrivert** és USB-szinten beragasztja az eszközt — lásd [docs/07-ismert-hibak.md](docs/07-ismert-hibak.md).
- A gyári lemezen 5 alváz-kar kombináció csomagjai vannak egy image-ben; a mi példányunkhoz **csak a `mini_mec_four_arm*` csomagok relevánsak** — a többihez generált kód ne nyúljon, ne is hivatkozzon rájuk.
- **2026-09-18 élő teszt: `/cmd_vel` és `/arm_cmd` megerősítve, szoftverlánc (soros port, STM32, IMU/odom 20Hz) egészséges.** Ha mégsem mozog a bázis — se webről, se fizikai joystickről —, az hardveres ok (E-stop gomb, külön motor-tápkapcsoló, alacsony akkufeszültség), nem szoftverhiba. Lásd [docs/08-kezi-vezerles.md](docs/08-kezi-vezerles.md) diagnosztika szakaszát. A robotkar gripper-értékének (`arm_cmd` `data[3]`) numerikus konvenciója még nincs kalibrálva — a kar-vezérlés addig MOCK-only marad.

## Licenc / szerzőség

Sári Bence (NeonPC / Neumann Robotics), 2026.
