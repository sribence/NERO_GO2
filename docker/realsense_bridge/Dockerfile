# realsense_bridge — Intel RealSense D435i szín+mélység adat kiadása ROS1
# Noetic-on keresztül (a robot natúr rendszerén már megvan a librealsense2
# könyvtár + a ROS1 realsense2_camera csomag driverje ehhez a pontos ARM64
# platformhoz, de a Python binding hiányzik és nincs internet mindig —
# ezért a driver-réteget itt, Docker-izoláltan, friss apt-telepítéssel
# hozzuk fel, a natúr rendszert egyáltalán nem érintve).
#
# A konténer:
#  1) elindítja a realsense2_camera ROS1 node-ot (szín + mélység + pontfelhő
#     topicok, TISZTA szenzorolvasás, sosem küld semmit a robotnak)
#  2) elindítja a rosbridge_websocket-et (:9091), hogy a web_dashboard
#     (roslibpy-vel, ugyanaz a minta, mint a SLAM/rosbridge bridge-nél)
#     ki tudja olvasni ezeket a topicokat.
#
# Ld. docs/00-BIZTONSAGI-SZABALYOK.md — a natúr /opt/ros/noetic-t NEM
# módosítjuk, ez egy teljesen külön, konténerben élő ROS1 telepítés.

FROM ros:noetic-ros-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-noetic-realsense2-camera \
    ros-noetic-rosbridge-suite \
    ros-noetic-compressed-image-transport \
    ros-noetic-image-transport \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 9091

# A realsense2_camera csak nyers (sensor_msgs/Image) topicot ad
# (/camera/color/image_raw) — a web_dashboard base64-JPEG-ként várja, ezért
# egy image_transport "republish" node konvertálja compressed formátumra.
#
# FONTOS: a ROS1 rosbridge_websocket egy futó roscore-hoz (master, :11311)
# próbál csatlakozni indításkor — ha nincs kifejezetten elindítva előtte,
# "Failed to contact master, Retrying..." hibával örökre retry-el, sosem
# nyitja meg a websocket portot. Ezért itt explicit ELŐSZÖR a roscore fut,
# és csak utána a két roslaunch/rosrun.
CMD ["/bin/bash", "-c", "\
    source /opt/ros/noetic/setup.bash && \
    roscore & \
    sleep 4 && \
    roslaunch realsense2_camera rs_camera.launch align_depth:=true enable_pointcloud:=true & \
    sleep 6 && \
    rosrun image_transport republish raw in:=/camera/color/image_raw compressed out:=/camera/color/image_raw & \
    roslaunch rosbridge_server rosbridge_websocket.launch port:=9091 & \
    wait \
"]
