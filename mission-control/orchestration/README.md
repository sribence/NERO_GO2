# orchestration (port 9104)

Task engine + protocol gateway. Lets other systems drive the robot
through a sequential task pipeline over REST, WebSocket, or MQTT — all
three funnel into the same `TaskEngine` (`task_engine.py`).

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `NAVIGATION_URL` | `http://navigation:9103` | base URL of the `navigation` pillar |
| `SENSORS_URL` | `http://sensors:9105` | base URL of the `sensors` pillar |
| `AUDIO_URL` | `http://audio:9107` | base URL of the `audio` pillar |
| `REDIS_HOST` / `REDIS_PORT` | `redis` / `6379` | event bus |
| `MQTT_BROKER_HOST` / `MQTT_BROKER_PORT` | `mqtt` / `1883` | MQTT bridge |

If Redis or the MQTT broker are unreachable at startup, the service logs a
warning and keeps running (REST/WS still work; MQTT retries with backoff
in the background).

## Step types

A task is `{"steps": [ {...}, {...}, ... ]}`. Steps execute strictly in
order; the task fails as soon as one step fails.

### `goto` — walk to a point via the `navigation` pillar

```json
{"goto": [1.5, -2.0], "timeout_s": 120, "poll_interval_s": 1.0}
```

Calls `POST {NAVIGATION_URL}/goto {"x":1.5,"y":-2.0}`, then polls
`GET {NAVIGATION_URL}/nav_status` until it reports `done`/`succeeded`
(success), `failed`/`error`/`aborted` (step fails), or `timeout_s` elapses
(step fails).

### `call_api` — call an external system and wait for its response

```json
{
  "call_api": {
    "url": "https://example.com/api/notify",
    "method": "POST",
    "body": {"msg": "robot arrived"},
    "headers": {"Authorization": "Bearer ..."}
  },
  "wait_for": "response",
  "timeout_s": 30
}
```

Makes the HTTP call and blocks until the response arrives or `timeout_s`
elapses (step fails on timeout or HTTP >= 400). The response body is
stored in the step's `result.response` in the task status.

### `sensor` — capture from the `sensors` pillar

```json
{"sensor": "photo"}
{"sensor": "lidar_scan"}
{"sensor": "thermal"}
```

Calls `POST {SENSORS_URL}/sensors/{photo|lidar_scan|thermal}` and stores
the response as the step result.

### `play_sound` — trigger the `audio` pillar

```json
{"play_sound": "task_complete"}
```

Calls `POST {AUDIO_URL}/audio/play/task_complete`.

## Full example task

```json
{
  "steps": [
    {"goto": [1.0, 0.0], "timeout_s": 60},
    {"sensor": "photo"},
    {
      "call_api": {"url": "https://example.com/hook", "method": "POST", "body": {"stage": "arrived"}},
      "timeout_s": 15
    },
    {"play_sound": "task_complete"}
  ]
}
```

## REST usage

```bash
curl -X POST http://localhost:9104/task \
  -H "Content-Type: application/json" \
  -d '{"steps":[{"goto":[1,0]},{"play_sound":"task_complete"}]}'
# => {"task_id": "..."}

curl http://localhost:9104/task/<task_id>/status
```

## WebSocket usage

Connect to `ws://localhost:9104/ws`. Send the same task JSON to enqueue a
task (server replies immediately with `{"task_id": ...}`), then step
events for **every** running task are pushed to all connected clients as
they happen:

```json
{"task_id": "...", "step_index": 0, "step_type": "goto", "status": "started", "detail": null, "t": 1234.5}
```

Example with `websocat`:

```bash
websocat ws://localhost:9104/ws
{"steps":[{"goto":[1,0]},{"play_sound":"task_complete"}]}
```

## MQTT usage

Publish a task JSON to `missioncontrol/task/submit`:

```bash
mosquitto_pub -h localhost -t missioncontrol/task/submit \
  -m '{"steps":[{"goto":[1,0]},{"play_sound":"task_complete"}]}'
```

Task events are published to `missioncontrol/task/events` (same shape as
the WS events / the `mc.orchestration.task_event` Redis channel).

## Events / logging

Every step transition (`started`/`succeeded`/`failed`) is:
1. appended to `logs/events.jsonl` (`{"t":..., "pillar":"orchestration", "level":"info", "msg":"...", "task_id":..., "step_index":..., "step_type":..., "status":..., "detail":...}`)
2. published to Redis channel `mc.orchestration.task_event`
3. published to MQTT topic `missioncontrol/task/events` (if broker connected)
4. broadcast to all connected `/ws` clients

## Known limitations

- WS clients see events for *all* tasks, not just the one they submitted
  (simplest correct behavior for a small number of trusted dashboard
  clients; add `task_id` filtering client-side, or extend the server to
  scope subscriptions, if that becomes a problem).
- The MQTT bridge uses a single shared client/thread and does not offer
  QoS/retry semantics beyond `paho-mqtt`'s defaults.
- `task_engine.py` runs each task in its own daemon thread (not a process
  pool); this is fine for the expected low task-submission rate of a
  single robot but doesn't parallelize CPU-heavy step work.
