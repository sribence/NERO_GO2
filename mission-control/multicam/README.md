# multicam (port 9106)

Pluggable multi-USB-camera manager: the robot's built-in "front" camera
(via `core/robot_client.py`) plus N additional USB cameras (side/rear/
night-vision) on the Jetson via `/dev/video*` passthrough.

Talks to the robot only through `core/robot_client.py`
(`ROBOT_BACKEND=mock|live`, default `mock`), per `CONVENTIONS.md`.

## Camera discovery

`GET /cameras` always registers the `core` robot client's own camera as
`cam_id="front"`, `source="robot_client"` -- this is what keeps the camera
list non-empty during mock/dev testing, even with zero USB cameras
attached.

On top of that, it scans `/dev/video*` (Linux/Jetson only) and registers
one `UsbCameraSource` per device node found, labeled `side`, `rear`,
`night_vision`, ... in discovery order (falling back to `usbN` for extras).
A USB camera that fails to open is marked `"available": false` rather than
crashing the service or being silently dropped from the list.

**On this Windows dev machine there is no `/dev/video*`**, so `GET
/cameras` will only ever show the single `front` (robot_client) camera --
that's expected, not a bug. To exercise the USB path locally you'd need
Linux with a real or virtual video device.

## Endpoints

### `GET /cameras`

```bash
curl http://localhost:9106/cameras
# [{"cam_id": "front", "source": "robot_client", "label": "front", "available": true}]
```

### `GET /cameras/{cam_id}/frame`

One JPEG frame.

```bash
curl http://localhost:9106/cameras/front/frame -o front.jpg
```

### `GET /cameras/{cam_id}/stream`

MJPEG multipart stream (`multipart/x-mixed-replace`), viewable directly in
a browser `<img src="http://localhost:9106/cameras/front/stream">` tag, or
via `GET /` below.

### `POST /cameras/{cam_id}/record/start` / `POST /cameras/{cam_id}/record/stop`

Continuous frame-saving to `recordings/<cam_id>/<timestamp>/frame_%06d.jpg`
in a background thread, at `RECORD_FPS` (env var, default `2`).

```bash
curl -X POST http://localhost:9106/cameras/front/record/start
# {"cam_id": "front", "recording": true, "out_dir": ".../recordings/front/20260910_101530", "fps": 2.0}

curl -X POST http://localhost:9106/cameras/front/record/stop
# {"cam_id": "front", "recording": false, "out_dir": "...", "frame_count": 14}
```

### `GET /`

Simple HTML page with one `<img>` tag per discovered camera pointed at its
`/stream` endpoint, for quick manual viewing in a browser.

## Logs

Every camera-list, frame, stream-start, and record start/stop event is
appended as one JSON line to `logs/events.jsonl`, per `CONVENTIONS.md`.

## Run locally (no Docker)

```bash
cd mission-control
pip install -r core/requirements.txt -r multicam/requirements.txt
set ROBOT_BACKEND=mock   # PowerShell: $env:ROBOT_BACKEND = "mock"
cd multicam
python app.py
```

Open `http://localhost:9106/` in a browser.

## Run in Docker (real deployment, with USB passthrough)

Build from the `mission-control/` repo root:

```bash
docker build -f multicam/Dockerfile -t mc-multicam .
```

For real USB cameras, pass the device nodes through in `docker-compose.yml`:

```yaml
services:
  multicam:
    build:
      context: .
      dockerfile: multicam/Dockerfile
    ports:
      - "9106:9106"
    environment:
      - ROBOT_BACKEND=live
      - RECORD_FPS=2
    devices:
      - /dev/video0:/dev/video0   # side
      - /dev/video1:/dev/video1   # rear
      - /dev/video2:/dev/video2   # night_vision
    volumes:
      - ./multicam/recordings:/app/multicam/recordings
      - ./multicam/logs:/app/multicam/logs
```

Without `devices:` passthrough, the container (like this Windows dev
machine) will only see the `front` robot_client camera -- that's the
graceful fallback, not a failure.
