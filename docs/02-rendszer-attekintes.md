# Rendszer áttekintés — Jetson dokk

## Hardver / platform

- **Chip:** NVIDIA Jetson Orin (Tegra234) — a device-tree nevek (`kernel_tegra234-p3767-0000-p3768-0000-a0.dtb`) Orin NX/Nano modult jeleznek
- **L4T (Linux for Tegra):** R35 (release), REVISION 3.1 → **JetPack 5.1.1**
- **Kernel:** `5.10.104-tegra` (aarch64)

## Operációs rendszer

```
NAME="Ubuntu"
VERSION="20.04.5 LTS (Focal Fossa)"
```

## Ismert előzmény

A `.bash_history` alapján ezen a példányon **korábban már volt kézi beavatkozás**:
- Kernel device-tree (`.dtb`) fájl kézi cseréje, mentés `.bk` kiterjesztéssel, majd reboot
- `dtc` (device-tree compiler) használata a dtb dekódolására
- `system_journal_normal_pc` csomag telepítése (`deploy.sh` futtatva) — ez adja a `sys_monitor.service`-t

Ez azt jelenti, hogy a jelen "natúr" állapot **nem feltétlenül 100%-ban gyári** — már történt rajta karbantartás/módosítás a korábbi tulajdonos vagy a Unitree support által, mielőtt hozzánk került.

## Rendszerszolgáltatások (systemd, futó állapotban)

| Service | Státusz | Funkció |
|---|---|---|
| `sys_monitor.service` | enabled, running | CPU/memória/hőmérséklet/hálózati késleltetés logolás (`/unitree/module/system_journal/sys_monitor.py`) |
| `unitree-upgrade.service` | enabled, running | a `:80`-as webes frissítő felület backendje |
| `nxserver.service` | running | NoMachine távoli asztal szerver |

## Futó folyamatok (2026-08-31-i pillanatkép, "nyugalmi" állapotban)

Nincs ROS/SLAM node futásban alapból — csak `sys_monitor.py` (root), `/upgradePythonServer/server.py` (root), és az SSH/session szolgáltatások (NoMachine, dbus, pulseaudio stb., amik a grafikus session részei). A SLAM/navigáció csak kézi indítással fut.

## Tárhely / Docker

Docker telepítve van, de **0 image, 0 konténer** — teljesen üres. Ez jó hír a Docker-alapú, szeparált fejlesztéshez (ld. [00-BIZTONSAGI-SZABALYOK.md](00-BIZTONSAGI-SZABALYOK.md)) — nincs mivel ütköznie.

## Perifériák

- `/dev/i2c-0` … `/dev/i2c-9` — I2C buszok jelen vannak
- `/dev/video*` — **üres**, nincs kamera-eszköz ezen a boardon (a kamera valószínűleg WebRTC-n megy közvetlenül a fej-modulból)
- USB — jelenleg semmi külső eszköz nincs bedugva (csak root hub-ok)
- Soros portok (`/dev/ttyUSB*`, `/dev/ttyACM*`) — nincs semmi csatlakoztatva
