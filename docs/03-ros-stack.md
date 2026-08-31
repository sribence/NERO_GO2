# ROS-stack

A Jetson dokkon **egyszerre két ROS-verzió** van telepítve — ez szokatlan, de a Go2 EDU ökoszisztémára jellemző (a gyári odometria-szolgáltatás ROS1-es, a SLAM/navigáció ROS2-es).

## ROS1 Noetic

- Telepítve: `/opt/ros/noetic`
- Ezt használja: `/unitree/module/Odometer_service` (vizuális-inerciális odometria, `rpg_svo_pro_open`/SVO-alapú, catkin workspace)
- `rosversion -d` → `noetic`

## ROS2 Foxy

- Telepítve: `/opt/ros/foxy`
- Ezt használja: `/unitree/module/graph_pid_ws` (a hozzáadott SLAM/LiDAR/Nav2 stack, ld. [05-egyedi-slam-stack.md](05-egyedi-slam-stack.md))

## CycloneDDS — a natív kommunikációs réteg

A Go2 **nem sima ROS-topicokon** kommunikál elsődlegesen, hanem egy natív DDS-rétegen (`rt/...` topic-nevekkel, ld. [04-gyari-unitree-szoftver.md](04-gyari-unitree-szoftver.md)). Ehhez saját CycloneDDS build készült:

- `~/cyclonedds_ws` — CycloneDDS 0.10.2 forrásból buildelve, `rmw_cyclonedds_cpp` a ROS2 middleware réteghez
- Config: `~/cyclonedds_ws/cyclonedds.xml`

Ez a réteg hidalja át a natív Unitree DDS-topicokat a ROS2 világ felé.

## Workspace-ek összefoglalva

| Workspace | ROS-verzió | Build-rendszer | Mit csinál |
|---|---|---|---|
| `~/cyclonedds_ws` | ROS2 (Foxy) | colcon | CycloneDDS + rmw réteg |
| `/unitree/module/Odometer_service` | ROS1 (Noetic) | catkin (catkin_tools) | vizuális-inerciális odometria (SVO) |
| `/unitree/module/graph_pid_ws` | ROS2 (Foxy) | colcon | LiDAR/SLAM/navigáció (egyedi, nem gyári) |

## Megjegyzés a `ros2` parancshoz

Fontos: `noetic` és `foxy` egyszerre sourceolása **konfliktust okoz** (a `ros2` parancs ilyenkor hibázik) — mindig csak az egyik ROS-verzió `setup.bash`-át source-oljuk egy adott shell-munkamenetben, sose mindkettőt egyszerre.
