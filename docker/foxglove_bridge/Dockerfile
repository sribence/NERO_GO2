# foxglove_bridge — forrásból buildelve ROS2 Foxy-ra
#
# A dustynv/ros:foxy-desktop-l4t-r35.3.1 image-re épül (már lehúzva a
# Jetsonon, ld. ../dev/README.md). A Docker Hub-on nincs előre buildelt
# foxglove_bridge Foxy-hoz (csak Noetic/Galactic), ezért forrásból
# fordítjuk — ez a natív rendszert egyáltalán nem érinti, minden a
# konténeren belül történik.

FROM dustynv/ros:foxy-desktop-l4t-r35.3.1

# Ismert hiba: a base image-ben a ROS2 apt-repó GPG-kulcsa lejárt/érvénytelen
# (2025-ös ROS-community probléma, a packages.ros.org kulcsrotációja miatt).
# Frissítjük a kulcsot, mielőtt apt-get update-et futtatnánk.
RUN apt-get update -o Acquire::AllowInsecureRepositories=true; \
    apt-get install -y --no-install-recommends curl gnupg2 || true
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /tmp/ros.key \
    && apt-key add /tmp/ros.key

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libwebsocketpp-dev \
    libasio-dev \
    nlohmann-json3-dev \
    ros-foxy-rosbag2 \
    ros-foxy-rosbag2-storage \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
RUN git clone --branch ros2 https://github.com/foxglove/ros-foxglove-bridge.git src/ros-foxglove-bridge

RUN /bin/bash -c "source /opt/ros/foxy/setup.bash && colcon build --symlink-install --packages-select foxglove_bridge foxglove_msgs"

CMD ["/bin/bash", "-c", "source /opt/ros/foxy/setup.bash && source /workspace/install/setup.bash && ros2 launch foxglove_bridge foxglove_bridge_launch.xml"]
