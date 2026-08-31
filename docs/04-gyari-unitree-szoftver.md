# Gyári Unitree szoftverstack (`/unitree/`)

A root szintű `/unitree/` könyvtár a gyári Unitree szoftverek helye (megkülönböztetendő a `~/unitree` felhasználói könyvtártól, amiben leletek/logok/dokumentumok vannak).

## `/unitree/lib/unitree_go2_sdk`

A natív C++ SDK, ezen belül:
- `unitree_go2_sdk/` — a tényleges SDK forrás (`CMakeLists.txt`, `example/`, `include/`, `lib/`, `bin/`)
- `rosidl_dds/`, `rosidl/` — DDS↔ROS IDL generáló eszközök
- `unitree_dds_idl/` — **a teljes natív DDS topic-katalógus**, IDL definíciókkal és JSON sémákkal

### DDS topic-katalógus (`unitree_dds_idl/go2/0TopicList.md`)

| Topic | Info |
|---|---|
| `rt/lowcmd` | alacsony szintű vezérlés |
| `rt/lowstate` | alacsony szintű állapot |
| `rt/lf/lowstate` | alacsony szintű állapot, 20Hz (láberő, ventilátor-fordulatszám) |
| `rt/sportmodecmd` | mozgás-vezérlési parancsok |
| `rt/sportmodestate` / `rt/lf/sportmodestate` | mozgás-állapot (utóbbi 20Hz) |
| `rt/frontvideostream` | elülső kamera H264 videó (WebRTC-n, nem DDS-en) |
| `rt/frontphotoreq` / `rt/frontphotores` | fotókészítés kérés/válasz (base64 JPEG) |
| `rt/utlidar/cloud` | nyers beépített LiDAR pontfelhő |
| `rt/utlidar/cloud_deskewed` | torzításmentesített pontfelhő |
| `rt/utlidar/voxel_map` | voxel-térkép |
| `rt/uwbstate` / `rt/uwbswitch` | UWB-alapú követés állapota/kapcsolója |
| `rt/wirelesscontroller` | távirányító adatok |
| `rt/webrtcreq` / `rt/webrtcres` | WebRTC kapcsolat kérés/válasz (app → felhő → mqtt → webrtc) |
| `rt/bashreq` / `rt/bashres` | **távoli bash-parancs végrehajtás DDS-en keresztül** — kalibráció, config-lekérdezés, távirányító-azonosító beállítás stb. |
| `rt/voiceconfig` | hangerő és LED-fényerő beállítás |

⚠️ A `rt/bashreq` topic azt jelenti, hogy a natív app-kapcsolaton keresztül **tetszőleges bash-parancs futtatható a robot vezérlőjén** — ezt biztonsági szempontból is érdemes szem előtt tartani.

## `/unitree/module/Odometer_service`

Vizuális-inerciális odometria (VIO), a `rpg_svo_pro_open` (SVO — Semi-direct Visual Odometry) könyvtárra épül, ROS1/catkin workspace. Ez adja a robot saját pozícióbecslését mozgás közben.

## `/unitree/module/system_journal`

`sys_monitor.py`, systemd service-ként fut folyamatosan. CPU, memória, hőmérséklet, hálózati késleltetés logolás — a logok dátum szerinti almappákba kerülnek (`log/sys_monitor/ÉÉÉÉ-HH-NN/...`).

## `/unitree/services/install.sh`

Generikus systemd-telepítő szkript: bemásolja a mappában lévő `.service` fájlokat `/etc/systemd/system/`-be, `daemon-reload`-ol, majd újraindítja őket. Ezzel települ pl. a `sys_monitor.service`.
