# Gyári szoftver — mi van a lemezen, mit használunk belőle

| Terület | Package / könyvtár | Használjuk? |
|---|---|---|
| Robot-alap, bringup, motor/IMU driverek | `~/wheeltec_robot` | **IGEN** — ez a fő belépési pont |
| Robotkar, MoveIt | `~/wheeltec_arm` | **IGEN** |
| LiDAR driverek | `~/wheeltec_lidar` | **IGEN** |
| SLAM: gmapping + Cartographer + ORB-SLAM2 | `~/cartographer_ws` | **IGEN** |
| Darknet, YOLOv5 (kétféle build), `ros_tensorflow` | — | részben |
| `ollama_chat_ros` — helyi LLM ROS-node | — | nem ehhez a projekthez |
| JetRacer sávkövetés, betanított modellekkel (`road_following_model_828_1.pth` stb.) | `~/jetracer` | referenciának jó kiindulópont |
| Autoware.AI teljes kutatási stack (LiDAR-detekció, sávfelismerés, útvonaltervezés) | `~/Autoware` | **NEM** — gyári referencia build, nincs jele robot-specifikus hangolásnak, mérete/komplexitása miatt inkább csak tanulmányozásra |
| Hangvezérlés (AIUI/xfyun ASR), automatikus visszatöltés | `auto_recharge_ros` | dokkolás-funkcióhoz hasznos lehet |

## Már telepített, tesztelt élő infrastruktúra

Ezek fel vannak telepítve és működnek — bármilyen saját fejlesztés építhet rájuk anélkül, hogy újra kellene telepíteni:

- **`rosbridge_suite`** (`ros-noetic-rosbridge-server`), `rosbridge_websocket` a **9090** porton
- **`web_video_server`** a **8080** porton (MJPEG stream-ek)
- **`fake-hwclock`** — megoldja az RTC-elem hiányából adódó "1970-es óra" problémát boot után, automatikusan

## Gyártói ajánlott fejlesztési sorrend

A gyártó saját dokumentációja szerint (forrás: [Wheeltec R550A Arm ROS and MoveIt Guide](https://openelab.io/blogs/learn/wheeltec-r550a-arm-ros-moveit-mobile-manipulation-guide), [wheeltec/docs](https://github.com/wheeltec/docs)) a pick-and-place **nem kész funkció** dobozból — csak építőelemek vannak hozzá:

1. Alap mozgásvezérlés és biztonság (`turn_on_wheeltec_robot` már ezt adja)
2. SLAM és autonóm navigáció (gmapping/Cartographer közül választani — mindkettő fent van)
3. Kar-közös mozgástervezés
4. MoveIt eljárások, ütközéselkerülés
5. Percepció-alapú objektumpóz-meghatározás (YOLO/tracking csomagok)
6. Koordinált pick-and-place viselkedés — ez a gyártó szerinti végcél

> "Az objektumdetektálás, grasping-kiválasztás, kalibrálás és helyreállítási logika továbbra is fejlesztést igényel." — a gyártó saját megfogalmazása.
