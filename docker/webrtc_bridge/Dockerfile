# NERO_GO2 WebRTC bridge — kamera + LiDAR + telemetria a hivatalos
# Unitree WebRTC protokollon (unitree_webrtc_connect, MIT licenc).
# Szeparált a robot natív rendszerétől, ld. ../../docs/00-BIZTONSAGI-SZABALYOK.md

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    portaudio19-dev \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libjpeg-dev \
    libpng-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py .

EXPOSE 5001

CMD ["python", "bridge.py"]
