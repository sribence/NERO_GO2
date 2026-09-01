# NERO_GO2

**Neumann Robotics — Unitree Go2 EDU dokumentáció**

Ez a repó a NeonPC/Neumann Robotics tulajdonában lévő **Unitree Go2 EDU** négylábú robot teljes körű, magyar nyelvű dokumentációja: hálózati felépítés, fedélzeti szoftverstack, ROS-ökoszisztéma, natív DDS-interfész, elérhető webes felületek, és a biztonságos üzemeltetés szabályai.

A cél egy folyamatosan bővülő, nyílt tudásbázis a robotról — amit bárki (csapattag, jövőbeli fejlesztő, vagy a nyílt közösség) használhat referenciaként, mielőtt hozzányúlna a rendszerhez.

## ⚠️ Mielőtt bármit csinálnál a robottal — olvasd el ezt

👉 **[docs/00-BIZTONSAGI-SZABALYOK.md](docs/00-BIZTONSAGI-SZABALYOK.md)**

Ez egy drága, nehezen pótolható konfigurációjú példány. A natív, gyári rendszer **érintetlen** kell maradjon — minden új funkció kizárólag Docker-konténerben, szeparáltan mehet fel rá.

## Tartalomjegyzék

- [docs/01-hálózat.md](docs/01-halozat.md) — IP-címek, portok, hogyan köss rá egy laptopot
- [docs/02-rendszer-attekintes.md](docs/02-rendszer-attekintes.md) — Jetson platform, OS, JetPack verzió
- [docs/03-ros-stack.md](docs/03-ros-stack.md) — ROS1 Noetic + ROS2 Foxy, CycloneDDS, workspace-ek
- [docs/04-gyari-unitree-szoftver.md](docs/04-gyari-unitree-szoftver.md) — `/unitree/` modulok, natív SDK, DDS topic-katalógus
- [docs/05-egyedi-slam-stack.md](docs/05-egyedi-slam-stack.md) — a hozzáadott LiDAR/SLAM/Nav2 workspace
- [docs/06-webes-feluletek.md](docs/06-webes-feluletek.md) — mi érhető el böngészőből
- [docs/07-internet-megosztas.md](docs/07-internet-megosztas.md) — hogyan adjunk (ideiglenesen) internetet a robotnak Windows laptopról
- [docs/08-foxglove-terv.md](docs/08-foxglove-terv.md) — élő adatmegjelenítés terve (Foxglove Studio)
- [docs/09-dds-interfesz-eltapasztalas.md](docs/09-dds-interfesz-eltapasztalas.md) — ismert hiba: a natív CycloneDDS config rossz interfészt (`eth0` vs `eth10`) ír elő
- [docs/10-munkamenet-naplo-2026-08-31.md](docs/10-munkamenet-naplo-2026-08-31.md) — mai munkamenet napló, nyitott TODO-k holnapra
- [docs/11-oktatocsomag-terv.md](docs/11-oktatocsomag-terv.md) — nagy vízió: webes irányítás, objektumkövetés, navigáció, oktatási demó — meglévő nyílt projektekre építve
- [docs/12-taszklista.md](docs/12-taszklista.md) — konkrét, sorrendbe rakott feladatlista fázisonként — **KEZDD ITT**, ha dolgozol a projekten
- [docs/00-BIZTONSAGI-SZABALYOK.md](docs/00-BIZTONSAGI-SZABALYOK.md) — üzemeltetési alapszabályok
- [docker/dev/](docker/dev/) — szeparált Docker fejlesztői környezet (ROS2 Foxy, L4T R35.3.1-illesztett image)
- [docker/rosbridge/](docker/rosbridge/) — `rosbridge_suite` (a `foxglove_bridge` helyett, mert az sosem támogatta a Foxy-t) — **build kész, de `network_mode: host`-on SIGSEGV-be fut, megoldatlan**
- [docker/webrtc_bridge/](docker/webrtc_bridge/) — kamera+LiDAR+telemetria a hivatalos WebRTC-protokollon — **élőben tesztelve: kamera+telemetria működik, LiDAR pontfelhő még nem**
- [docker/web_dashboard/](docker/web_dashboard/) — fő webes vezérlőpult, joystick+akció-gombok+arm/disarm biztonsági zár — **élőben tesztelve: DDS-kapcsolat+telemetria működik, mozgás még nincs kipróbálva**
- [docs/13-lokalis-llm-delegalas.md](docs/13-lokalis-llm-delegalas.md) — hogyan generálódik a kód helyi Qwen2.5-Coder modellel, Claude-review-val
- [foxglove/](foxglove/) — Foxglove Studio layout/config a robot élő adatainak megjelenítéséhez
- [backups/](backups/) — konfig-pillanatképek + Docker image mentések

## Gyors infó

| | |
|---|---|
| Modell | Unitree Go2 EDU |
| Jetson dokk | `192.168.123.18` (SSH: `unitree`/`123`) |
| Mozgásvezérlő board | `192.168.123.161` |
| Platform | NVIDIA Jetson Orin, JetPack 5.1.1 (L4T R35.3.1) |
| OS | Ubuntu 20.04.5 LTS |
| ROS | ROS1 Noetic + ROS2 Foxy (mindkettő telepítve) |
| Feltérképezés dátuma | 2026-08-31 |

## Backups

A [backups/](backups/) mappa a robot Jetson dokkjáról készült, nem-destruktív **konfiguráció-pillanatképeket** tartalmazza (netplan, systemd service fájlok, csomaglista). **Ez nem teljes lemezkép** — csak referencia a jelenlegi működő állapotról.

## Licenc / szerzőség

Sári Bence (NeonPC / Neumann Robotics), 2026.
