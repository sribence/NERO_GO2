# sensors (port 9105)

On-demand sensor command endpoints -- single snapshots, not continuous
streams. For live/continuous multi-camera capture, see the `multicam`
pillar (port 9106).

Talks to the robot only through `core/robot_client.py`
(`ROBOT_BACKEND=mock|live`, default `mock`), per `CONVENTIONS.md`.

## Endpoints

### `POST /sensor/photo`

Captures one frame via `robot.get_camera_frame(cam_id)`, saves it to
`captures/photo_<timestamp>.jpg`, and serves it back over `/captures/`.

Optional query param `cam_id` (default `"front"`).

```bash
curl -X POST http://localhost:9105/sensor/photo
# {"path": "/app/sensors/captures/photo_20260910_101530_123.jpg",
#  "url": "/captures/photo_20260910_101530_123.jpg"}
curl -O http://localhost:9105/captures/photo_20260910_101530_123.jpg
```

### `POST /sensor/lidar_scan`

Captures one dense point-cloud snapshot via `robot.get_lidar_points()`,
saves it as a JSON array of `[x, y, z]` points to
`captures/lidar_<timestamp>.json`.

```bash
curl -X POST http://localhost:9105/sensor/lidar_scan
# {"path": "/app/sensors/captures/lidar_20260910_101545_456.json", "point_count": 180}
```

### `POST /sensor/thermal`

**Deliberate, honest stub.** There is no thermal camera hardware on the
robot yet -- it's explicitly deferred in the project plan. This endpoint
always returns:

```bash
curl -X POST http://localhost:9105/sensor/thermal
# HTTP 501
# {"error": "no thermal hardware configured yet",
#  "note": "Thermal camera support is explicitly deferred ..."}
```

The code is structured so adding real hardware later is a one-class change,
not a rewrite: `ThermalCapture` is an abstract interface
(`is_configured()`, `capture()`), and `NotConfiguredThermalCapture` is the
only implementation today. To add a real USB thermal cam:

1. Write a new subclass, e.g. `SeekThermalCapture(ThermalCapture)`, backed
   by the vendor SDK or a v4l2/OpenCV grab of the thermal video device.
2. Swap the module-level `thermal_capture = NotConfiguredThermalCapture()`
   for `thermal_capture = SeekThermalCapture()`.
3. `POST /sensor/thermal` starts returning real captures immediately --
   the endpoint logic already handles the "configured" path (saves to
   `captures/thermal_<timestamp>.jpg`, logs, returns `{"path", "url"}`).

## Logs

Every capture attempt (success or failure) is appended as one JSON line to
`logs/events.jsonl`, per `CONVENTIONS.md`:

```json
{"t": 1757501730.12, "pillar": "sensors", "level": "info", "msg": "photo captured", "cam_id": "front", "path": "...", "bytes": 4213}
```

## Run locally (no Docker)

```bash
cd mission-control
pip install -r core/requirements.txt -r sensors/requirements.txt
set ROBOT_BACKEND=mock   # PowerShell: $env:ROBOT_BACKEND = "mock"
cd sensors
python app.py
```

Service listens on `0.0.0.0:9105`.

## Run in Docker

Build from the `mission-control/` repo root (needs `core/` in the build context):

```bash
docker build -f sensors/Dockerfile -t mc-sensors .
docker run -p 9105:9105 -e ROBOT_BACKEND=mock mc-sensors
```
