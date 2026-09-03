# Érzékelők és aktuátorok

## Alváz

Mecanum kerekek, 4 motor. Az alváz saját mikrovezérlő-firmware-rel rendelkezik, amivel soros protokollon kommunikál a Jetson (`turn_on_wheeltec_robot` package).

## LiDAR

2D lézer-szkenner, `/scan` topicon publikál (`sensor_msgs/LaserScan`). Driverek a lemezen: `rplidar_ros`, `lslidar_cx_driver`. Mért adat: kb. **1665 sugár/körbefordulás**, ebből tipikusan ~950 érvényes beltérben.

## Astra RGBD kamera (fő szenzor, az alvázon)

Orbbec Astra, `astra_camera` ROS driver.

- `/camera/rgb/image_raw` — színkép
- `/camera/depth/image_raw` — **16UC1 nyers mélységkép** (nem színes!)
- `/camera/depth/points` — `sensor_msgs/PointCloud2`, mért: ~307200 pont (640×480), ebből tipikus beltéri jelenetben ~37000 érvényes
- `/camera/ir/image_raw` — infravörös

**Driver-korlát:** az IR és az RGB nem futhat egyszerre. A driver naplója szerint "Infrared and Color streams are enabled. Infrared stream will be disabled."

**Élő kapcsolók:** a driver `std_srvs/SetBool` service-eket ad ki: `/camera/toggle_color`, `/camera/toggle_depth`, `/camera/toggle_ir`.

**🔴 VESZÉLYES:** a `/camera/toggle_ir` hívása összeomlasztja a teljes `astra_camera` node-ot és az USB-eszközt beragadt állapotban hagyja. Lásd [07-ismert-hibak.md](07-ismert-hibak.md) a pontos tünetért és a javításért.

## Wheeltec C70 kamera (a robotkarra szerelve)

Generikus UVC webkamera, "Integrated Webcam" néven jelentkezik be, egy kis USB hub-boardon át.

- Elérés: `rosrun usb_cam usb_cam_node _video_device:=/dev/RgbCam _pixel_format:=yuyv`
- Topic: `/usb_cam/image_raw`, 640×480
- **Alapból NEM indul el** a gyári bringuppal — külön node kell hozzá (benne van a `scripts/start_feeds.sh`-ban).

## Robotkar

4 szabadságfok + megfogó. MoveIt konfiguráció megvan: `mini_mec_four_arm_moveit_config`. Gyári pick-and-place csomag: `wheeltec_arm_pick` (referenciának jó, de a megfogási szekvenciát saját, paraméterezhető logikára kell cserélni — innen a "Pickerbot" név, de a pick-and-place gyárilag nem kész funkció).

**4 DOF következménye:** tetszőleges 6D póz nem érhető el. A munkatér korlátos, a megfogási orientáció kötött — pozíció-alapú IK-t kell használni, nem teljes póz-IK-t.

## Mért teljesítményadatok (a saját irányítópultból)

- Astra RGB + Depth egyszerre: ~30 Hz
- Pontfelhő: 307200 pontból ~37000 érvényes tipikus beltéri jelenetben
- LiDAR: 1665 sugárból ~950 érvényes
- A böngészőben a pontfelhő 6-os lépésközzel ritkítva még folyékonyan forog
