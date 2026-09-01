# rosbridge

Élő adatmegjelenítés a Foxglove Studio-hoz — WebSocket-alapú JSON API a ROS2 topicokra (`ros-foxy-rosbridge-suite`, port 9090).

## Miért nem `foxglove_bridge`

Az eredeti terv a `foxglove_bridge` csomagot forrásból építette volna (ld. korábbi verziók a git történetben), de kiderült, hogy ez a projekt **soha nem támogatta hivatalosan a ROS2 Foxy-t** — a legkorábbi kiadásai is csak Galactic/Humble/Rolling-ot céloztak (forrás: a projekt README-jének minden vizsgált verziója, 0.2.1-től 0.6.4-ig). A build strukturális API-inkompatibilitás miatt hibázott (`CMake Error: Could not find catkin`), nem javítható egyszerű patch-csel.

Helyette a `rosbridge_suite`-ot használjuk:
- hivatalosan támogatja a Foxy-t
- **előre buildelt apt-csomagként** elérhető (`ros-foxy-rosbridge-suite`, packages.ros.org-on) — nincs szükség forrásból fordításra
- a Foxglove Studio natívan tudja kezelni "Rosbridge (ROS 1 & 2)" kapcsolattípusként

## Használat

```bash
docker compose up --build
```

Foxglove Studio-ban: **Open connection → Rosbridge (ROS 1 & 2)** → `ws://192.168.123.18:9090`

## Ismert korlát

A rosbridge JSON-over-WebSocket protokollja kevésbé hatékony, mint a natív `foxglove_bridge` bináris protokollja — nagy adatmennyiségnél (pl. LiDAR pontfelhő, `rt/utlidar/cloud`) érdemes figyelni a késleltetésre/CPU-terhelésre. Ha ez gondot okoz élesben, alternatíva lehet egy `foxglove_bridge` build **Humble**-re (nem Foxy-ra) egy külön konténerben — de ez egy nagyobb, külön eldöntendő lépés lenne.

## ⚠️ KRITIKUS, MEGOLDATLAN HIBA (2026-09-01): SIGSEGV valódi hálózati interfészen

Élő teszt közben kiderült egy súlyos, platform-szintű probléma:

- **Docker alap `bridge` hálózaton** (virtuális `veth` interfész, NAT mögött) a `ros2 topic list` és a rosbridge is **hibátlanul fut**.
- Amint a konténer a **valódi fizikai `eth10` NIC-et** látja közvetlenül — akár `network_mode: host`, akár dedikált `macvlan` hálózaton keresztül — **minden ROS2/rclpy-folyamat azonnal szegfaultol** (`exit code 139` / `SIGSEGV`), **RMW-implementációtól függetlenül** (ugyanúgy összeomlik alap FastRTPS-szel és `rmw_cyclonedds_cpp`-vel is).
- Ez **nem** a korábban feltételezett "több interfész közti ambiguity" hiba (a `macvlan` teszt egyetlen interfésszel is összeomlott), hanem valószínűleg a generikus (nem Jetson-specifikus) `focal/arm64` ROS2-csomagok és a Realtek RTL8111 fizikai NIC driver/interfész-metaadatai közötti mélyebb inkompatibilitás.
- **Következmény:** a `network_mode: host` — ami a robot valós DDS multicast-discovery-jéhez szükséges lenne (`rt/...` topicok látásához) — **jelenleg nem használható** ezzel az image-alappal. Bridge hálózaton viszont a konténer nem éri el a robot DDS-multicast forgalmát, tehát a natúr `rt/...` topicok nem lesznek láthatók.

**Nyitott TODO — nem lezárt, tovább vizsgálandó:**
- [ ] `dmesg`/`journalctl` valódi stack trace-ének megszerzése a pontos hibás library azonosításához (jelenleg csak `exit code 139`-et látunk, konkrét backtrace nélkül)
- [ ] Jetson-specifikus (JetPack/L4T-illesztett) `rmw_cyclonedds_cpp`/`ros-foxy-*` csomagok keresése a generikus Ubuntu focal/arm64 build helyett (pl. dusty-nv jetson-containers ökoszisztémában lehet ilyen)
- [ ] Alternatíva: ne a konténeren belül fusson a rosbridge, hanem a natív rendszeren (ez viszont ütközne a "natúr rendszerbe ne nyúljunk" szabállyal — csak végső esetben, user jóváhagyással)
- [ ] Alternatíva: `docker network create -d ipvlan` kipróbálása `macvlan` helyett (más kernel-modul, más driver-interakció lehet)

## Előzmény

Az eredeti (elavult) terv és a hozzá tartozó GPG-kulcs javítás dokumentálva: [docs/13-lokalis-llm-delegalas.md](../../docs/13-lokalis-llm-delegalas.md), [docs/10-munkamenet-naplo-2026-08-31.md](../../docs/10-munkamenet-naplo-2026-08-31.md).
