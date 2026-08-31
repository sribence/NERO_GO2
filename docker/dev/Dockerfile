# NERO_GO2 fejlesztői konténer
#
# Alapja: dustynv/ros:foxy-desktop-l4t-r35.3.1 — ez pontosan a robot Jetson
# dokkjának L4T verziójához (R35.3.1 / JetPack 5.1.1) illesztett, előre
# buildelt ROS2 Foxy image a jetson-containers projektből (dusty-nv).
#
# FONTOS: ez a konténer teljesen szeparált a robot natív rendszerétől.
# Semmit nem telepítünk a hoszton — minden csomag/könyvtár ide, a
# konténerbe kerül. Ld. ../../docs/00-BIZTONSAGI-SZABALYOK.md

FROM dustynv/ros:foxy-desktop-l4t-r35.3.1

# Fejlesztői kényelmi eszközök (csak a konténeren belül)
RUN apt-get update && apt-get install -y --no-install-recommends \
    vim \
    curl \
    iproute2 \
    net-tools \
    tmux \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

CMD ["/bin/bash"]
