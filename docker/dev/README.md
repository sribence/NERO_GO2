# NERO_GO2 fejlesztői konténer

Ez egy **teljesen szeparált** Docker-alapú fejlesztői környezet a Unitree Go2 EDU Jetson dokkjához. A robot natív rendszerét (ROS Noetic+Foxy telepítés, `/unitree/` gyári modulok, `cyclonedds_ws`) **semmilyen formában nem módosítja** — ld. [../../docs/00-BIZTONSAGI-SZABALYOK.md](../../docs/00-BIZTONSAGI-SZABALYOK.md).

## Alap image

`dustynv/ros:foxy-desktop-l4t-r35.3.1` — a [dusty-nv/jetson-containers](https://github.com/dusty-nv/jetson-containers) projekt előre buildelt, **pontosan a robot L4T verziójához (R35.3.1 / JetPack 5.1.1) illesztett** ROS2 Foxy image-e. Ez azért fontos, mert egy nem-illeszkedő CUDA/L4T verziójú image-ből a GPU-gyorsítás nem működne.

## Miért `network_mode: host`

A CycloneDDS multicast-alapú node-discovery nem jut át rendesen a Docker alapértelmezett bridge-hálózatán/NAT-ján. Ezért a konténer a hoszt hálózati névterét használja (`network_mode: host`) — ez **kizárólag hálózati** megosztás, a fájlrendszert/csomagkezelést semmiben nem érinti, a konténer így is teljesen külön van a natív szoftverkörnyezettől.

## Ismert hiba, amit korrigálunk

A natív `~/cyclonedds_ws/cyclonedds.xml` a Jetsonon **`eth0`** interfészt ír elő, de a tényleges interfész neve ezen a gépen **`eth10`**. Ez azt jelenti, hogy a gyári DDS-discovery valószínűleg rossz/nem létező interfészre próbál kötni. A konténer ezért egy **saját, helyesbített** configot használ (`cyclonedds.container.xml`, `eth10`-zel) — a natív fájlt nem piszkáljuk.

## Használat

A robot Jetson dokkján (SSH: `unitree@192.168.123.18`), miután ez a mappa átmásolásra/klónozásra került rá:

```bash
cd docker/dev
docker compose build
docker compose run --rm dev
```

Konténeren belül:
```bash
source /opt/ros/foxy/setup.bash
ros2 topic list
```

## Saját kód

A `workspace/` mappa a konténerbe `/workspace/src` alá van mountolva — ide kerül minden fejlesztés alatt álló saját ROS2 csomag/kód. Ez a mappa a git repóban verziózva van, tehát a fejlesztés nyomon követhető és megosztható.

## Leállítás / eltávolítás

```bash
docker compose down
docker image rm nero_go2/dev:foxy-l4t-r35.3.1
```

Ez **semmit nem hagy maga után** a hoszt natív rendszerén — csak a Docker saját image/konténer tárolóját érinti, amit maga a `docker` parancs kezel, függetlenül a natív ROS/rendszer-telepítéstől.
