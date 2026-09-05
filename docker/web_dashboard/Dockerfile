# NERO_GO2 web dashboard — szeparált a robot natív rendszerétől.
# Ld. ../../docs/00-BIZTONSAGI-SZABALYOK.md
#
# unitree_sdk2py (hivatalos: unitreerobotics/unitree_sdk2_python) natív
# CycloneDDS-t igényel PONTOSAN 0.10.2 verzióban, forrásból fordítva —
# ehhez a robot natúr rendszerén MÁR létező build-et használjuk fel
# (~/cyclonedds_ws/install/cyclonedds), amit a build előtt bemásolunk a
# build contextbe (ld. README "Build előfeltétel" szakasz) — ez NEM
# módosítja a natúr rendszert, csak OLVASSuk a meglévő buildjét.

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# A natúr rendszer meglévő CycloneDDS 0.10.2 build-je (bemásolva a build
# context-be a build.sh/README lépései szerint, mielőtt docker build fut).
COPY cyclonedds_home /opt/cyclonedds
ENV CYCLONEDDS_HOME=/opt/cyclonedds
ENV LD_LIBRARY_PATH=/opt/cyclonedds/lib:${LD_LIBRARY_PATH}

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# unitree_sdk2py nincs (megbízhatóan) publikálva a PyPI-n — a hivatalos
# forrásból telepítjük, ami ugyanezt a CYCLONEDDS_HOME-ot használja fel.
RUN pip install --no-cache-dir "git+https://github.com/unitreerobotics/unitree_sdk2_python.git"

COPY app.py .
COPY mock_streams.py .
COPY mock_thermal.py .
COPY templates/ templates/
COPY static/ static/

EXPOSE 5002

CMD ["python", "app.py"]
