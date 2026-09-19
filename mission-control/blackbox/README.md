# blackbox (port 9108)

The mission-control "flight recorder": a small, bounded, self-pruning
rolling buffer of telemetry + camera frames that survives crashes/incidents
by promoting the relevant slice to permanent storage *before* it would be
pruned.

## What it does

Four background threads (started at import time, alongside the FastAPI app):

- **recorder** -- every `RECORD_INTERVAL_SECONDS` (~1s) polls
  `robot.get_pose()` / `get_battery()` / `get_imu()` via `core/robot_client.py`
  and appends a JSON line to `buffer/rolling.jsonl`. Every
  `FRAME_INTERVAL_SECONDS` (~5s) it also grabs one JPEG frame into
  `buffer/frames/<unix_ts>.jpg`.
- **pruning** -- every `PRUNE_INTERVAL_SECONDS` enforces the retention
  policy: deletes the oldest log lines / frame files once either
  `RETENTION_SECONDS` (age) or `MAX_BUFFER_MB` (total size) is exceeded.
  Logic lives in `retention.py` (`prune_buffer`), independent of FastAPI.
- **anomaly** -- watches the same telemetry the recorder just captured and
  flags an anomaly when:
  - (a) battery percent drops faster than `BATTERY_DROP_PCT_PER_SEC`,
  - (b) IMU `accel_z`/`roll`/`pitch` jumps beyond threshold between
    consecutive samples ("impact"),
  - (c) telemetry polling itself fails `POLL_FAILURE_THRESHOLD` times in a
    row, or goes silent for too long (robot/process looks dead -- same
    idea as `_watchdog()` in `docker/web_dashboard/app.py`),
  - (d) an external trigger arrives: `POST /incident/trigger` or a message
    on the Redis `mc.core.anomaly` channel.
- **redis subscriber** -- subscribes to `mc.core.anomaly` (CONVENTIONS.md)
  as another incident-trigger source. If Redis is unreachable this logs a
  warning and retries every 5s -- it never crashes the service.

On any anomaly, `trigger_incident()` (in `app.py`, backed by
`retention.promote_incident()`) copies the last `INCIDENT_WINDOW_SECONDS`
of `buffer/rolling.jsonl` lines + `buffer/frames/*.jpg` into a permanent
`incidents/<timestamp>_<reason>/` folder (log + frames + `meta.json`), so
that slice is no longer subject to pruning. Auto-detected anomalies are
debounced per-reason by `ANOMALY_COOLDOWN_SECONDS` so a persisting
condition doesn't spam a new incident every tick; a manual
`POST /incident/trigger` always creates one (`force=True`).

The service's own operational log goes to `logs/events.jsonl` (CONVENTIONS.md
format) -- this is separate from `buffer/rolling.jsonl`, which is the robot
telemetry buffer it manages, not its own logs.

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `ROBOT_BACKEND` | `mock` | `mock` or `live`, per `core/robot_client.py` |
| `REDIS_HOST` | `redis` | Redis host for the event bus |
| `REDIS_PORT` | `6379` | Redis port |
| `RETENTION_SECONDS` | `600` | Max age of rolling-buffer content |
| `MAX_BUFFER_MB` | `200` | Max total size of `buffer/` (log + frames) |
| `INCIDENT_WINDOW_SECONDS` | `30` | How much history to promote into an incident |
| `RECORD_INTERVAL_SECONDS` | `1.0` | Telemetry poll interval |
| `FRAME_INTERVAL_SECONDS` | `5.0` | Camera-frame capture interval |
| `PRUNE_INTERVAL_SECONDS` | `5.0` | How often the pruning loop runs |
| `ANOMALY_CHECK_INTERVAL_SECONDS` | `1.0` | How often the anomaly loop checks |
| `ANOMALY_COOLDOWN_SECONDS` | `30` | Debounce window per anomaly reason |
| `POLL_FAILURE_THRESHOLD` | `5` | Consecutive poll failures -> "robot_unresponsive" |
| `BATTERY_DROP_PCT_PER_SEC` | `2.0` | Battery-percent drop rate that counts as anomalous |
| `ACCEL_Z_JUMP_THRESHOLD` | `3.0` | m/s^2 jump in accel_z between samples -> "impact" |
| `ROLL_PITCH_JUMP_THRESHOLD_RAD` | `0.5` | rad jump in roll/pitch between samples -> "impact" |

## Endpoints

- `POST /incident/trigger {"reason": "..."}` -- manually promote the last
  `INCIDENT_WINDOW_SECONDS` into a new incident (e.g. an external E-stop).
- `GET /incidents` -- list saved incidents (id/reason/timestamp/counts).
- `GET /incidents/{id}` -- full incident detail: log lines + frame URLs.
  Frames are also served as static files under `/incidents_files/{id}/frames/...`.
- `GET /buffer/status` -- current buffer size (MB), oldest/newest telemetry
  timestamp, and the active retention settings.
- `GET /health` -- trivial liveness check.

## Running it standalone (no Docker, no Redis needed)

```bash
cd mission-control/blackbox
pip install -r requirements.txt -r ../core/requirements.txt
python app.py
```

It starts on `http://localhost:9108` with `ROBOT_BACKEND=mock` by default.
If Redis isn't reachable you'll see a `"redis subscribe loop error, will
retry"` warning line in `logs/events.jsonl` every 5s -- the rest of the
service (recording, pruning, anomaly detection, incidents API) works fine
without it.

## Trying it with curl

```bash
# buffer status
curl http://localhost:9108/buffer/status

# manually trigger a test incident
curl -X POST http://localhost:9108/incident/trigger \
     -H "Content-Type: application/json" \
     -d '{"reason": "manual_test"}'

# list incidents
curl http://localhost:9108/incidents

# incident detail (use an id from the list above)
curl http://localhost:9108/incidents/<incident_id>
```

## Verifying pruning actually deletes files (manual test)

1. Start the service with a tiny retention window so pruning is visible
   within seconds instead of minutes:

   ```bash
   RETENTION_SECONDS=10 MAX_BUFFER_MB=200 python app.py
   ```

2. In another terminal, watch the buffer grow then shrink back down:

   ```bash
   # frame count / rolling.jsonl size over time
   ls blackbox/buffer/frames | wc -l
   wc -l blackbox/buffer/rolling.jsonl
   ```

   Run those two commands every few seconds. For the first ~10s both
   numbers climb (1 log line/s, 1 frame/5s). After ~10s, `PRUNE_INTERVAL_SECONDS`
   (default 5s) kicks in and you'll see `wc -l rolling.jsonl` stop growing
   and start hovering around ~10 lines, and old files under `buffer/frames/`
   actually disappear from `ls` -- not just get ignored, the files are gone
   from disk (`os.remove` / a rewritten `rolling.jsonl`, see `retention.py:prune_buffer`).
   `logs/events.jsonl` will also show `"pruned buffer"` info lines with
   `removed_log_lines`/`removed_frames` counts whenever something was
   actually deleted.

3. To see the size cap prune instead of the age cap, set a very small
   `MAX_BUFFER_MB` (e.g. `MAX_BUFFER_MB=1` with `RETENTION_SECONDS=600`)
   and watch the same files disappear once the buffer crosses ~1MB, well
   before the 600s age limit would have removed anything.

## Known simplifications / limitations

- `prune_buffer`'s size-based pass rewrites `rolling.jsonl` from scratch
  when it removes lines (simple `os.replace` after writing a temp file).
  Fine at this scale (buffers bounded to `MAX_BUFFER_MB`, default 200MB);
  would want a smarter incremental approach if that cap grew much larger.
  Frame deletion (`os.remove`) is always O(1) per file, not a rewrite.
- Anomaly detection compares only *consecutive* samples (1s apart by
  default) -- a slow-building problem spread over many samples under the
  per-sample threshold will not trigger. Thresholds are env-tunable if the
  defaults prove too sensitive/insensitive against real hardware.
- Incident promotion is a *copy*, not a move -- the rolling buffer keeps
  recording normally through an incident, so a second overlapping anomaly
  shortly after the first still has real telemetry to promote.
- No auth on any endpoint -- same as the other pillars in this repo; the
  whole mission-control stack is assumed to run on a private/tailnet
  network (see `remote/`), not exposed publicly.
