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
| IP | `192.168.0.100` (fix, közvetlen Ethernet-kábelen a laptophoz) |
| SSH | kulcsos, jelszó nélkül — `wheeltec@192.168.0.100`, kulcs: `~/.ssh/pickerbot_mini` |
| Sudo jelszó | `dongguan` (gyári alapértelmezett — ugyanaz, mint a Wi-Fi hotspot jelszava) |
| Státusz | élő, tesztelt irányítópult 2026-08-25 óta; oktatási platform terve kész, generálása folyamatban |

## ⚠️ Mielőtt hozzányúlnál

- **USB-C a Jetsonon adatport, nem tápbemenet.** Csak a barrel jack (19V) vagy a robot saját akkuja indítja el.
- **Az `/camera/toggle_ir` service hívása összeomlasztja a kameradrivert** és USB-szinten beragasztja az eszközt — lásd [docs/07-ismert-hibak.md](docs/07-ismert-hibak.md).
- A gyári lemezen 5 alváz-kar kombináció csomagjai vannak egy image-ben; a mi példányunkhoz **csak a `mini_mec_four_arm*` csomagok relevánsak** — a többihez generált kód ne nyúljon, ne is hivatkozzon rájuk.

## Licenc / szerzőség

Sári Bence (NeonPC / Neumann Robotics), 2026.
