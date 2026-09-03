# Futtatás a roboton (SSH-n at): ssh -i ~/.ssh/pickerbot_mini wheeltec@192.168.0.100 'bash -s' < start_feeds.sh
# Elinditja: roscore, Astra RGB+depth+IR kamera, C70 kamera (kar), LiDAR, web_video_server, rosbridge_websocket

source /opt/ros/noetic/setup.bash
source ~/wheeltec_lidar/devel/setup.bash
source ~/wheeltec_robot/devel/setup.bash

nohup roscore < /dev/null > /tmp/roscore.log 2>&1 &
sleep 4

nohup roslaunch turn_on_wheeltec_robot wheeltec_camera.launch < /dev/null > /tmp/camera.log 2>&1 &
nohup roslaunch turn_on_wheeltec_robot wheeltec_lidar.launch < /dev/null > /tmp/lidar.log 2>&1 &
sleep 6

nohup rosrun usb_cam usb_cam_node _video_device:=/dev/RgbCam _image_width:=640 _image_height:=480 _pixel_format:=yuyv _camera_frame_id:=c70_cam _io_method:=mmap < /dev/null > /tmp/usbcam_c70.log 2>&1 &
nohup rosrun web_video_server web_video_server < /dev/null > /tmp/webvideo.log 2>&1 &
nohup roslaunch rosbridge_server rosbridge_websocket.launch < /dev/null > /tmp/rosbridge.log 2>&1 &
sleep 3

echo "=== rostopic list ==="
rostopic list
echo "SCRIPT_DONE"

# Dashboard (minden feed egy oldalon): scripts/dashboard.html, helyi HTTP szerverrol nyitva (python -m http.server 8901), NE file://-kent
# Kamerak nyersen: http://192.168.0.100:8080/
