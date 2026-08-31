# Élő adatmegjelenítés terve — Foxglove Studio

## Cél

Egy "eye-catching", élő dashboard Windows laptopról, ami a robot valós idejű adatait mutatja: IMU, akkumulátor, láberő, LiDAR pontfelhő, kamera-kép, mozgásállapot.

## Jelenlegi állapot (2026-08-31)

- **Nincs semmi előre telepítve** ehhez a gyári rendszeren (sem `foxglove_bridge`, sem `rosbridge_suite`).
- A natív webes felület (`unitree-upgrade`, ld. [06-webes-feluletek.md](06-webes-feluletek.md)) csak firmware-frissítésre való, nem adatmegjelenítésre.
- Az apt-cache-ben `ros-noetic-foxglove-bridge` elérhető (ROS1-hez), de **ROS2 Foxy-hoz nincs előre buildelt bridge-csomag** ebben az indexben.

## Két lehetséges út

### A) Foxglove Studio natív ROS2/DDS kapcsolat — telepítés nélkül

A Foxglove Studio desktop app tud natívan csatlakozni ROS2 DDS-hez, ha egyezik a `ROS_DOMAIN_ID` és a hálózat engedi a multicast discovery-t. Ez **nem igényel semmit a roboton** — érdemes elsőként ezt kipróbálni a laptopról.

**Kockázat:** nulla — a robot rendszeréhez nem nyúlunk, csak a laptopon futtatunk egy appot, ami hallgatja a hálózatot.

### B) `foxglove_bridge` Docker-konténerben

Ha az (A) nem működik (pl. multicast nem jut át, vagy explicit websocket-bridge kell), akkor a `foxglove_bridge` ROS2 node-ot **Docker-konténerben** futtatjuk a Jetsonon — a natív rendszert nem érinti, csak a konténer csatlakozik a meglévő ROS2/DDS hálózathoz.

Mivel nincs előre buildelt Foxy-csomag, a konténeren belül forrásból kell buildelni (vagy egy már meglévő, publikus `foxglove_bridge` Docker image-et használni, ha van Foxy-kompatibilis).

Ehhez kell:
1. Internet a Jetsonon (ld. [07-internet-megosztas.md](07-internet-megosztas.md))
2. Docker image build/pull — **szigorúan konténeren belül**, a hoszt rendszerét nem módosítva
3. A konténer csatlakoztatása a `cyclonedds_ws` DDS hálózatához (host network mode szükséges lehet a DDS discovery miatt — ezt körültekintően kell megcsinálni, mert a host network mode csökkenti az izolációt; alternatíva: explicit CycloneDDS unicast-konfiguráció konténeren belül, multicast/host-network nélkül)

## TODO

- [ ] Kipróbálni az (A) opciót — natív DDS kapcsolat Foxglove Studio-ból, telepítés nélkül
- [ ] Ha nem megy: eldönteni, hogy Noetic (ROS1, korlátozott adatkör) vagy Foxy (ROS2, teljes LiDAR/SLAM-kör) bridge-et építünk
- [ ] Docker image megtervezése a `foxglove_bridge`-hez (Foxy alapú, forrásból build vagy meglévő image)
- [ ] Hálózati izoláció kérdésének eldöntése (host network vs. explicit unicast DDS config)
