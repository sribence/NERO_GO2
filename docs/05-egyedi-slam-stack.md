# Egyedi SLAM/navigációs stack (`/unitree/module/graph_pid_ws`)

Ez **nem gyári alapfelszereltség** — valaki (korábbi tulajdonos, vagy a Unitree support egy egyedi projekt keretében) ráépített egy komplett LiDAR-alapú SLAM/navigációs ROS2 workspace-t.

## Indítás

```bash
cd /unitree/module/graph_pid_ws && source install/setup.bash
ros2 run QT_Server UnitreeSlam
```
(script: `0_unitree_slam.sh`)

## Csomagok (`src/`)

| Csomag | Funkció |
|---|---|
| `HesaiLidar_General_ROS-ROS2` | Hesai LiDAR driver |
| `livox_ros_driver2` | Livox LiDAR driver |
| `lio_sam_ros2` | LiDAR-Inertial Odometry and Mapping — komoly SLAM algoritmus |
| `nav2_costmap` | Nav2 navigációs stack — costmap komponens |
| `occ_grid_mapping` | occupancy grid térképezés |
| `dog_control` | robot-vezérlési logika |
| `go2_control_by_sdk` | vezérlés a natív SDK-n keresztül |
| `send_cmd` | parancsküldő util |
| `pid_tracing` | PID-hangolás/nyomkövetés |
| `task` | feladat-logika |
| `template_matching` | sablon-illesztés (valószínűleg vizuális/térkép-alapú lokalizációhoz) |
| `QT_Server` | a fő SLAM-indító node (`UnitreeSlam`) |
| `unitree_go`, `unitree_interfaces`, `custom_interface`, `graph_msg`, `graph_process` | üzenettípusok/interfészek |

## Mit jelent ez

A jelen példány fel van készítve **külső LiDAR-alapú SLAM-re és Nav2 navigációra** — nem csak a gyári beépített LiDAR (`rt/utlidar/*`) és a vizuális odometria (`Odometer_service`) van rajta, hanem egy teljes, komoly navigációs stack is (Hesai/Livox driver + LIO-SAM + Nav2).

**Nyitott kérdés:** hogy pontosan milyen fizikai LiDAR van/volt csatlakoztatva (Hesai vagy Livox típusú), és hogy ez a stack le van-e fordítva/futtatható-e jelenleg — ezt még nem ellenőriztük (`colcon build` állapota, `install/` mappa tartalma nem lett részletesen átnézve).

**TODO:** ellenőrizni a `graph_pid_ws/install/` és `build/` mappák állapotát, kideríteni, hogy a workspace jelenleg futtatható-e, és ha van fizikailag csatlakoztatható LiDAR, tesztet végezni vele (csak Docker-izolációban, ld. [00-BIZTONSAGI-SZABALYOK.md](00-BIZTONSAGI-SZABALYOK.md)).
