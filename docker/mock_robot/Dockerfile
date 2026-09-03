# mock_robot — a webrtc_bridge HTTP API-jának hamis, szintetikus-adatos
# másolata. Ld. README.md: miért kell ez.

FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mock_bridge.py .

EXPOSE 5001

CMD ["python", "mock_bridge.py"]
