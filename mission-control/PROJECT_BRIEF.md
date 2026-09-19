# Projekt-brief — Go2 Mission Control (kitöltött szerep-sablon)

_Ezt a fájlt egy külső/jövőbeli AI-szereplőhöz ("senior csapat" persona) írt kontextus-sablon kitöltéseként hoztam létre, hogy bármelyik jövőbeli munkamenet innen tudja átvenni a projekt valós állapotát. Minden alább szereplő állítás a repó tényleges kódjából/dokumentációjából és a mai (2026-09-10) fejlesztői munkamenet éles teszteredményeiből származik — nem feltételezés._

## SZEREP

Tapasztalt senior csapatként dolgozz, aki egyszerre:
- robotikai szoftverarchitekt (ROS 1/2, DDS/CycloneDDS, SLAM, útvonaltervezés),
- Unitree Go2 szakértő (`unitree_sdk2py`, sport mode API, WebRTC-kapcsolat, beépített LiDAR),
- full-stack fejlesztő (Python/FastAPI backend, three.js/vanilla JS frontend, WebSocket, MQTT, Docker),
- UI/UX tervező, ipari operátori felületekre (HMI) specializálódva,
- biztonsági és megbízhatósági mérnök (safety, security, hibakezelés).

A projekt jelentős részét AI (Claude Code, több párhuzamos agenttel) generálta — kezeld gyanakodva: ellenőrizz minden feltételezést, API-hívást és állítást, mielőtt élesben (fizikai roboton) bármit futtatnál.

## PROJEKT KONTEXTUS

**Cél:** enterprise szintű irányító alkalmazás Unitree Go2 robothoz — `mission-control` néven, a `NERO_GO2` dokumentációs repó egy önálló al-modulja. Autonóm padló+fal térképezés, kattints-a-térképre navigáció, multi-protokoll task-orchestration (WebSocket/MQTT/REST, külső rendszerek API-jainak hívása+várakozása), on-demand szenzor-parancsok, multi-USB-kamera, esemény-vezérelt hang, "feketedoboz" naplózás, Tailscale távoli elérés, és egy induló Unity-szerű 3D digitális iker operátori felület.

**Robot változat:** Unitree **Go2 EDU** (nem Pro/Air) — beépített LiDAR + Intel RealSense D435i mélységkamera (EDU-specifikus), plusz egy extra Hesai PandarXT-16 külső LiDAR.

**ROS verzió és disztribúció:** a robot Jetson dokkján **ROS1 Noetic ÉS ROS2 Foxy egyszerre telepítve** (nem egységes/modern ROS2 Humble-stack), saját buildelt CycloneDDS 0.10.2, Ubuntu 20.04.5 LTS, JetPack 5.1.1 (L4T R35.3.1). **A `mission-control` modul explicit NEM megy rá a ROS2 rétegre** — a `rosbridge_suite`-tal korábban SIGSEGV-be futott `network_mode: host` alatt valódi hálózati interfészen (megoldatlan, ismert hiba), ezért a robot-kommunikáció két bevált, ROS-t megkerülő útvonalon megy: (1) a hivatalos WebRTC-protokoll (`webrtc_bridge`, kamera+LiDAR+telemetria), (2) a natív `unitree_sdk2py` DDS SportClient (mozgás), közvetlenül CycloneDDS felett, `rclpy`/`rmw` réteg nélkül.

**Tech stack:**
- Backend: Python 3.11, FastAPI + uvicorn minden pillérben, `paho-mqtt`, `redis` (pub/sub event bus), `requests`, OpenCV (`opencv-python-headless` a multicam pillérben), `Pillow`.
- Frontend: vanilla JS + three.js (CDN, build-lépés nélkül) a `digital-twin` 3D nézetben; a fő repó `web_dashboard`-ja Flask+Jinja+vanilla JS.
- Infrastruktúra: Docker Compose (9 mikroszolgáltatás + Redis + Mosquitto MQTT), Tailscale (userspace-networking, Docker-only).
- Repó: `C:\dev\NERO_GO2` (lokális klón), `github.com/sribence/NERO_GO2` (upstream).

**Célfelhasználók és környezet:** kettős cél. (1) Rövid távon oktatási/bemutató célú kirakat egyetemistáknak/érdeklődőknek (a meglévő `web_dashboard /showcase` 3D digitális iker demó). (2) Középtávon a user (Sári Bence, NeonPC/Neumann Robotics) saját, enterprise-igényű operátori irányítópultja — távoli (Tailscale-en át) parancsadás, feladat-orchestration külső rendszerekkel, feketedoboz-naplózás incidens-visszakereséshez.

**Ami működik (élőben tesztelve, 2026-09-04/05 és 2026-09-10):**
- WebRTC kamera+telemetria+beépített LiDAR élő robotnál (`docker/webrtc_bridge`).
- DDS SportClient kapcsolat, élő telemetria, WASD+joystick mozgásvezérlés (`docker/web_dashboard`).
- Log-odds occupancy-grid SLAM + alap pont-navigáció kezdeménye a fő repóban.
- `mission-control` mind a 9 pillére egyenként, plain Python-folyamatként, `ROBOT_BACKEND=mock` mellett: valódi frontier-exploration bolyongás, A*-navigáció, teljes task-motor (WS+MQTT+REST), fotó/LiDAR-snapshot mentés, multi-kamera discovery+stream+felvétel, esemény-vezérelt hang, feketedoboz gördülő puffer+valódi auto-törlés+incidens-export, three.js 3D nézet élő kattints-a-térképre navigációval.
- `core` szolgáltatás HTTP-proxy rétege, amivel több különálló folyamat/konténer **egy közös, megosztott** robot-állapotot lát (két külön Python-processzel élőben leellenőrizve).

**Ami nem működik / ismert hibák:**
- **Docker Compose teljes stack indítása ezen a fejlesztői Windows gépen jelenleg blokkolva**: a Docker Desktop telepítve van, de a WSL2/"Virtual Machine Platform" Windows-funkció nincs bekapcsolva, ennek engedélyezése admin-jogosultságot + újraindítást igényel, ami a usernél most nem elérhető. → 9 db elszigetelt konténer helyett egyelőre csak kézi/plain-Python multi-processz teszt történt.
- `rosbridge_suite` `network_mode: host`-on SIGSEGV-be fut valódi hálózati interfészen — megoldatlan, ezért a `mission-control` tudatosan nem erre épül.
- Intel RealSense D435i — valódi USB hardver-hiba (`RS2_USB_STATUS_PIPE`), nincs másik USB-port a roboton, parkoltatva.
- Vendor `graph_pid_ws`/`send_cmd` natív SLAM-lokalizáció — hiányzó szimbólum (`free_iox_chunk`), nincs hozzá forráskód, zsákutcaként elengedve, saját ROS-mentes térképező pipeline épült helyette.
- Hőkamera (`sensors/thermal`, `multicam` hőkamera-ág) — nincs beszerzett hardver, tudatos, dokumentált stub.
- `digital-twin` relokalizáció (ICP-alapú "hol vagyok" újra-megtalálás) — szimulált/fix konfidencia-értékkel, a valódi LiDAR-scan-match még nincs bekötve.
- Tailscale — a Docker-service definiálva van, de nincs auth-key-jel csatlakoztatva (user-döntés, nem automatizált).
- A `mapping`/`navigation` pillérek `level_id` (szint/lépcső-címkézés) mezője jelenleg map-szinten van, nem cellánként — a többszintes térkép még csak séma-szinten előkészített, funkcionálisan nem teljes.
- A mock-robot WiFi/IMU-viselkedése soha nem generál elég éles pitch/z-változást ahhoz, hogy a `StairDetector` lépcső-heurisztikáját éles roboton kívül tesztelni lehessen.

**Tesztelési lehetőség:** jelenleg **csak szimuláció** (`ROBOT_BACKEND=mock`) ezen a fejlesztői gépen — van fizikai Go2 EDU robot, de nincs hozzá most közvetlen hozzáférés/aktív Ethernet-kapcsolat ebben a munkamenetben, és a teljes Docker Compose stack sem futtatható a fenti WSL2-blokkoló miatt. Élő robotos + teljes 9-konténeres végigtesztelés a következő, Docker-képes/robot-elérésű munkamenetre halasztva — ld. `mission-control/STATUS.md` a pontos parancsokért, amint az akadály elhárul.

---

Futtatási lehetőségek és tesztelési módok részletesen: **[STATUS.md](STATUS.md)**.
Architektúra, pillér-leírások, extra ötletlista: **[README.md](README.md)**.
Fejlesztői konvenciók (robot-kliens interfész, map-séma, Dockerfile-minta): **[CONVENTIONS.md](CONVENTIONS.md)**.
