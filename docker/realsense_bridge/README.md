# realsense_bridge

Az Intel RealSense D435i (a robot fejére szerelt mélységkamera) szín-képét és
mélység-pontfelhőjét teszi elérhetővé a `web_dashboard`/`showcase` oldal
számára — Docker-izoláltan, a natúr rendszert nem érintve.

## Miért ROS1 Noetic ebben a konténerben

A robot natúr rendszerén már telepítve van a `ros-noetic-realsense2-camera`
csomag (egy korábbi setup része) — ez a pontos ARM64/Jetson platformra
lefordított, bizonyítottan működő driver. A Python binding (`pyrealsense2`)
viszont hiányzik, és nincs rá előre buildelt ARM64 wheel a PyPI-n (csak
forrásból fordítható, ami hosszú build). Ezért ahelyett, hogy natívan
telepítenénk bármit, vagy source-ból fordítanánk a bindinget, egy KÜLÖN,
Docker-izolált ROS1 Noetic image-ben ugyanazt a bevált apt-csomagot
telepítjük (`ros-noetic-realsense2-camera` + `ros-noetic-rosbridge-suite`),
és a websocketen (rosbridge, `:9091`) keresztül olvassuk ki az adatot a
`web_dashboard`-ból (`roslibpy`-vel, ugyanaz a minta, mint a SLAM/`rosbridge`
bridge-nél, ld. `../rosbridge/`).

## USB-passthrough

A RealSense D435i nem tiszta USB Video Class (UVC) eszköz — a librealsense2
saját, alacsonyabb szintű USB-vezérlést is használ (firmware-parancsok,
mélység-kalibráció). Ezért a `docker-compose.yml` `privileged: true` +
`/dev/bus/usb` mountot használ (a hivatalos Intel RealSense Docker-példák
is ezt javasolják) — host-hálózat NEM kell, csak a `:9091` port van kitéve.

## Indítás

```bash
docker compose up -d --build
```

Ellenőrzés:
```bash
curl -s http://localhost:9091  # rosbridge websocket, HTTP GET-re hibát ad, de kapcsolat próbaként jó
```

A `web_dashboard`-nak be kell állítani a `REALSENSE_ROSBRIDGE_HOST=localhost`
(host network esetén) env-változót, hogy a `/realsense_data` SSE-végpont
tényleg olvassa ezt.
