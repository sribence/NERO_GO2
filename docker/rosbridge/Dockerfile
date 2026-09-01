# rosbridge — élő adatmegjelenítés Foxglove Studio-hoz
#
# FONTOS VÁLTÁS (2026-09-01): az eredeti terv a `foxglove_bridge` csomagot
# forrásból építette volna, DE kiderült, hogy ez a projekt SOHA nem
# támogatta hivatalosan a ROS2 Foxy-t (a legkorábbi kiadásai is csak
# Galactic/Humble/Rolling-ot céloztak) — ezért a colcon build
# "Could not find catkin" és hasonló hibákkal elszállt, strukturális
# API-inkompatibilitás miatt, nem javítható egyszerű patch-csel.
#
# Helyette a `rosbridge_suite`-ot használjuk, ami:
# - hivatalosan támogatja a Foxy-t, ELŐRE BUILDELT apt-csomagként elérhető
#   (ros-foxy-rosbridge-suite, packages.ros.org-on)
# - a Foxglove Studio natívan tudja kezelni "Rosbridge (ROS 1 & 2)"
#   kapcsolattípusként (JSON-over-WebSocket, port 9090)
#
# A dustynv/ros:foxy-desktop-l4t-r35.3.1 image-re épül (már lehúzva a
# Jetsonon, ld. ../dev/README.md) — a natív rendszert egyáltalán nem
# érinti, minden a konténeren belül történik.

FROM dustynv/ros:foxy-desktop-l4t-r35.3.1

# Ismert hiba: a base image-ben a ROS2 apt-repó GPG-kulcsa lejárt/érvénytelen
# (2025-ös ROS-community probléma, a packages.ros.org kulcsrotációja miatt).
# FONTOS: ez az image a /usr/share/keyrings/ros-archive-keyring.gpg dedikált
# keyring-fájlt használja (signed-by=... az /etc/apt/sources.list.d/ros2.list-ben),
# NEM a régi apt-key trusted.gpg tárolót — ezért a kulcsot közvetlenül ebbe a
# fájlba kell írni, különben az apt-key add néma no-op marad.
RUN apt-get update -o Acquire::AllowInsecureRepositories=true; \
    apt-get install -y --no-install-recommends curl gnupg2 || true
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /tmp/ros.key \
    && gpg --batch --yes --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg /tmp/ros.key

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-foxy-rosbridge-suite \
    ros-foxy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*
# A base image alapból csak FastRTPS RMW-t tartalmaz. A robot natív DDS-rétege
# (rt/... topicok) CycloneDDS-t használ (ld. ../../docs/09-dds-interfesz-eltapasztalas.md) —
# a rmw_cyclonedds_cpp nélkül a konténer nem látná ezeket a topicokat.

EXPOSE 9090

CMD ["/bin/bash", "-c", "source /opt/ros/foxy/setup.bash && ros2 launch rosbridge_server rosbridge_websocket_launch.xml"]
