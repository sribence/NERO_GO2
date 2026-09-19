# navigation (port 9103)

Click-to-goal path planning over the map the `mapping` pillar produces.
`POST /goto {x, y}` fetches the current map from `mapping`, runs A* over
the floor layer (inflated by a robot-radius safety margin), and drives the
robot along the resulting waypoints in a background thread with a simple
heading-corrector. The endpoint returns immediately with a `nav_id`;
poll `GET /nav_status` for progress.

## Files

- `app.py` — FastAPI service, background nav-execution thread, Redis
  `mc.core.anomaly` publishing on stuck navigation, JSONL logging.
- `astar.py` — pure, dependency-free A* (`astar`, `build_blocked_grid`,
  `nearest_free_cell`, `world_to_grid`/`grid_to_world`,
  `is_stair_cell`). No FastAPI/robot/HTTP imports, directly unit
  testable: grid arrays in, cell path out.

## Endpoints

- `POST /goto {"x": float, "y": float}` — starts planning+driving to the
  goal in the background. Returns `202 {nav_id, state:"planning"}`, or
  `409` if the robot is not armed.
- `POST /goto/cancel` — cancels the current navigation and stops the
  robot.
- `GET /nav_status` — `{nav_id, state, goal, remaining_path, error}`,
  `state` one of `idle | planning | moving | blocked | done | failed |
  cancelled`.
- `POST /_debug/arm` / `POST /_debug/disarm` — local testing convenience,
  same reasoning as in `mapping/README.md` (each pillar owns its own
  `RobotClient` process instance).

## Stairs handling

Cells whose wall-layer height bucket falls in a "ramp/stair edge" band
(`NAV_STAIR_WALL_MIN..NAV_STAIR_WALL_MAX`, default `30..120`) are
excluded from A*'s obstacle set — and from being a *source* of obstacle
inflation — even if the floor layer marked them occupied, so a staircase
never blocks planning. The executor slows to `NAV_STAIR_SPEED` while the
robot's current cell is in that band; the Go2's native gait handles the
actual stair-climbing at the firmware level, this pillar only avoids
refusing to plan across it.

(The task description also asks for treating cells whose `level_id`
differs from the robot's current cell as non-blocking. Since the wire map
schema in `CONVENTIONS.md` carries a single top-level `level_id` per map —
not a per-cell field — `GET /map` only ever returns one level's grid at a
time, so this clause is currently a no-op: there is no mixed-level grid
for A* to plan across. See `mapping/README.md` for how multi-level maps
are stored.)

## Getting stuck

If a `/goto` remains in `moving` state with no measurable progress toward
the goal for more than `NAV_STUCK_WARN_S` (default 10s), the service
publishes one `mc.core.anomaly` event and reports `state: "blocked"`; if
progress resumes it goes back to `moving`. If there is still no progress
after `NAV_STUCK_FAIL_S` (default 30s) the navigation is given up on and
reported as `failed`.

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `ROBOT_BACKEND` | `mock` | `mock` or `live` |
| `REDIS_HOST` | `redis` | Redis host for `mc.core.anomaly` |
| `MAPPING_URL` | `http://localhost:9102` | where to `GET /map` (docker-compose sets `http://mapping:9102`) |
| `ROBOT_RADIUS_M` | `0.25` | obstacle-inflation safety margin |
| `NAV_FORWARD_SPEED` | `0.4` | m/s on normal ground |
| `NAV_STAIR_SPEED` | `0.12` | m/s while crossing a stair-band cell |
| `NAV_YAW_KP` | `1.4` | heading-correction gain |
| `NAV_WAYPOINT_TOL_M` | `0.12` | meters, waypoint-reached tolerance |
| `NAV_TICK_S` | `0.1` | control loop period |
| `NAV_STUCK_WARN_S` / `NAV_STUCK_FAIL_S` | `10.0` / `30.0` | seconds |
| `NAV_STAIR_WALL_MIN` / `NAV_STAIR_WALL_MAX` | `30` / `120` | wall-layer height-bucket band treated as stairs |

## Try it (against the mock backend, no physical robot needed)

Run `mapping` first (navigation needs its `/map`), explore a bit so
there's something to plan over, then:

```bash
cd navigation
ROBOT_BACKEND=mock MAPPING_URL=http://localhost:9102 python app.py
# in another shell:
curl -X POST http://localhost:9103/_debug/arm
curl -X POST http://localhost:9103/goto -H "Content-Type: application/json" -d '{"x":1.0,"y":1.0}'
curl http://localhost:9103/nav_status
curl -X POST http://localhost:9103/goto/cancel
```

Via docker-compose (from the `mission-control/` root, `MAPPING_URL` is
already wired to `http://mapping:9102`):

```bash
docker compose up --build mapping navigation redis
curl -X POST http://localhost:9102/_debug/arm
curl -X POST http://localhost:9102/explore/start   # build up some map first
curl -X POST http://localhost:9103/_debug/arm
curl -X POST http://localhost:9103/goto -H "Content-Type: application/json" -d '{"x":1.0,"y":1.0}'
```

## Known limitations / deliberate simplifications

- Unknown (`-1`) floor cells are treated as **passable** by A* (only
  confirmed-occupied `100` cells are obstacles). This is the optimistic
  choice so an incomplete map doesn't strand the robot with nowhere
  reachable; it does mean a `/goto` into truly unmapped territory can
  walk the robot into something `mapping` hasn't seen yet. A
  conservative/optimistic mode toggle would be a natural follow-up.
- Path execution is a point-and-shoot heading corrector along the raw
  A* waypoints (one per grid cell), not a smoothed pure-pursuit
  controller — simple and robust for a first pass, but not the shortest
  or smoothest physical trajectory.
- The "differing `level_id`" stairs clause is a no-op given the current
  single-level-per-map wire schema — see the Stairs handling section
  above.
- `/goto` re-fetches the map once at the start of planning; it does not
  continuously re-plan against `mapping`'s live updates while driving
  (only the stuck-detector reacts to real-world trouble). A full
  replanning loop is a natural extension once both pillars are
  integration-tested together.
