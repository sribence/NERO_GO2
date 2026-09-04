# hesai_bridge — Hesai PandarXT-16 UDP point-cloud dekóder és HTTP API.
# Ld. hesai_bridge.py fejléce a bájt-szintű formátum forrásáért.

FROM python:3.11-slim

WORKDIR /app
COPY hesai_bridge.py .

EXPOSE 2368/udp
EXPOSE 5003

CMD ["python", "hesai_bridge.py"]
