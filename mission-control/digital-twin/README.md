# digital-twin (port 9110)

The long-term, Unity-like 3D operator console for the Go2 mission-control
stack. This is a genuinely working **first version**, not an architecture
doc: it renders the real dual-layer map from `mapping`, shows the real
live pose from `core`, and lets an operator click the 3D floor to issue a
real `POST /goto` to `navigation`.

## What's real right now

- **`server.py`** — FastAPI service on `:9110`.
  - `GET /` — serves `static/index.html`.
  - `GET /api/map_proxy` — server-side proxy of `mapping`'s `GET /map`
    (env `MAPPING_URL`, default `http://mapping:9102`), cached ~300ms so
    the browser and the `/ws/live` loop don't hammer `mapping`. Returns
    503 with `{"error": ...}` if `mapping` isn't reachable — the UI
    catches this and shows a "waiting for mapping service..." banner
    instead of crashing.
  - `GET /api/pose_proxy` — proxies `core`'s `GET /state` (env
    `CORE_URL`, default `http://core:9101`) and returns just the `pose`
    field. Also fails soft (503 + JSON error) if `core` isn't up.
  - `POST /api/goto` — straight passthrough to `navigation`'s
    `POST /goto` (env `NAVIGATION_URL`, default `http://navigation:9103`),
    body `{"x": <float>, "y": <float>}`. Fails soft (503) if `navigation`
    isn't up.
  - `WS /ws/live` — pushes `{"pose": ..., "map_version": ..., "pose_error":
    ..., "map_error": ...}` to every connected browser every ~500ms
    (polling the proxies above server-side), so the browser never polls
    HTTP directly for live updates.
  - `GET /api/localization_confidence` — see "Explicitly deferred" below.
- **`static/index.html` + `static/app.js`** — a single-page vanilla JS +
  three.js (loaded from cdnjs, no build step, no npm) app that:
  - Renders the `floor` layer as a heightmap-flat, color-coded plane
    (dark gray = unknown/-1, teal = free/0, red = occupied/>=50), built
    from a `CanvasTexture` sized `width x height` and placed in world
    units using `resolution`/`origin_x`/`origin_y`.
  - Renders the `walls` layer as an `InstancedMesh` of boxes, one per
    grid cell where `walls[i] > 0`, height-scaled by the 0-255 bucket
    value, sitting on top of the floor plane at the correct world
    position.
  - Shows a live robot marker (sphere + cone "heading arrow") driven by
    the `/ws/live` pose feed, including yaw rotation.
  - **Click-to-navigate, working end to end**: click anywhere on the
    rendered floor -> three.js raycasts against the floor mesh -> the
    hit point is converted from scene space back to world `(x, y)` using
    the same `resolution`/`origin_x`/`origin_y` transform -> the app
    `POST`s `/api/goto {x, y}` -> the HUD shows "accepted" or "nav
    unavailable" depending on the response. A small orange ring marks the
    last-clicked target on the floor.
  - An on-screen HUD panel: WS connection status (live / reconnecting /
    disconnected, with auto-reconnect + backoff), current pose
    `x, y, yaw, level_id`, map size/resolution, map coverage % (fraction
    of cells that are not `-1`), and the outcome of the last goto click.
  - A confidence badge (top-right) polling
    `GET /api/localization_confidence` every 2s.
  - Camera: drag to orbit, scroll to zoom (hand-rolled, no
    `OrbitControls` import needed — kept dependency-free per the CDN
    constraints). A click is disambiguated from a drag by total pointer
    movement, so orbiting doesn't accidentally fire a goto.
  - Coordinate convention (documented in `app.js` too): world `(x, y)`
    maps directly to scene `(x, z)` with scene `y` as "up". This is an
    internally-consistent flattening, not a calibrated compass heading —
    fine for an operator console, worth revisiting if a real North-up
    convention matters later.

## Explicitly deferred

- **Real ICP-based relocalization.** `GET /api/localization_confidence`
  currently returns a **fixed/simulated** value
  (`{"confidence": 0.5, "simulated": true}`) — see the
  `# TODO(phase-4)` comment directly above the endpoint in `server.py`.
  The real version needs `mapping` to expose raw LiDAR scans so a live
  scan can be matched (ICP) against the stored map to detect "robot
  vacuum re-finding itself" style relocalization and derive a true
  confidence score, plus comparing LiDAR-implied position against
  dead-reckoning drift. The UI badge and the endpoint's response shape
  already exist so later phases can swap the implementation without
  touching the frontend contract.
- **Any direct robot access.** This pillar never imports
  `core/robot_client.py` — it only talks HTTP to `core`/`mapping`/
  `navigation`, per its role as a pure viewer/proxy.
- **Redis event bus.** `mc.mapping.map_update` is not subscribed to yet;
  freshness currently comes from polling `mapping` every ~500ms via
  `/ws/live` instead. Wiring the Redis subscription (per
  `CONVENTIONS.md`) to push-invalidate the map cache immediately instead
  of polling is a natural follow-up, not required for this pass to work.
  `logs/events.jsonl` (JSONL per `CONVENTIONS.md`) is still written for
  proxy failures and goto calls, for the `blackbox` pillar to pick up
  later.
- **True north-up / multi-level switching.** `level_id` is shown in the
  HUD but the viewer doesn't yet let an operator switch between levels or
  align the scene to a real-world compass heading.

## Running it standalone (without docker-compose)

```bash
cd digital-twin
pip install -r requirements.txt -r ../core/requirements.txt
# optional: point at real service hosts if not using default docker DNS names
set MAPPING_URL=http://localhost:9102
set CORE_URL=http://localhost:9101
set NAVIGATION_URL=http://localhost:9103
python server.py
```

Then open `http://localhost:9110/` in a browser.

If `mapping`/`core`/`navigation` aren't up yet, the page still loads: the
HUD shows "disconnected"/"reconnecting" for the WS, the pose fields stay
`--`, and a "waiting for mapping service..." banner appears instead of a
blank or broken 3D view. Once those services come up (in any order,
mid-session), the viewer picks them up automatically on the next
poll/WS tick — no page reload needed.

## Manual verification (curl)

```bash
curl http://localhost:9110/api/map_proxy
curl http://localhost:9110/api/pose_proxy
curl -X POST http://localhost:9110/api/goto -H "Content-Type: application/json" -d "{\"x\": 1.0, \"y\": 2.0}"
curl http://localhost:9110/api/localization_confidence
```
