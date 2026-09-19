# mapping (port 9102)

Autonomous "wander and map" engine for the Go2, robot-vacuum style.
Produces a dual-layer occupancy grid:

- **floor** — traversability layer (`-1` unknown / `0` free / `100`
  occupied), built with a log-odds Bresenham ray-trace from the robot's
  pose to every LiDAR point.
- **walls** — vertical-obstacle height layer (`0..255`), bucketed from
  each LiDAR point's z-height, independent of the floor decision (so a
  waist-height shelf still shows up as a tall obstacle even if it's above
  the floor layer's blocking band).

Frontier exploration: on each tick the service integrates the latest
LiDAR scan, then does a single BFS over reachable free cells to find the
*nearest* free cell that still touches an unknown cell (a frontier),
drives there with a simple heading-corrector while continuously
re-scanning, and repeats until no frontier remains (or `/explore/stop`).

Multi-level (stairs) support: a sustained IMU pitch excursion that
settles back to level is treated as evidence the robot changed floors.
Since the wire map schema (CONVENTIONS.md) carries a single top-level
`level_id`, each detected level gets its own internal grid (`MapStore`)
instead of a per-cell level field — `GET /map` always serves the
currently active level; pass `?level_id=level_1` to fetch an already-seen
one.

## Files

- `app.py` — FastAPI service + background exploration thread + Redis
  publishing + JSONL logging.
- `mapping_core.py` — pure, dependency-free grid/log-odds/frontier/BFS
  logic (`OccupancyGrid`, `MapStore`, `integrate_scan`,
  `next_frontier_target`, `StairDetector`, `bresenham_line`,
  `height_bucket`). No FastAPI/robot/Redis imports, directly unit
  testable.

## Endpoints

- `GET /map[?level_id=...]` — current (or a specific) level's map, exact
  schema from `CONVENTIONS.md`.
- `POST /explore/start` — starts the background wander-and-map loop.
  Returns `409` if the robot is not armed.
- `POST /explore/stop` — stops exploration and halts the robot.
- `GET /explore/status` — `{state, level_id, levels, cells_explored,
  coverage_percent, total_cells, last_error}`.
- `POST /_debug/arm` / `POST /_debug/disarm` — local testing convenience.
  Each pillar owns its own `RobotClient` instance (own process), so
  arming via `core`'s `/arm` (port 9101) does **not** arm this service's
  mock robot — not part of `CONVENTIONS.md`, purely for curl-testing.

## Env vars

| Var | Default | Meaning |
|---|---|---|
| `ROBOT_BACKEND` | `mock` | `mock` or `live`, per `core/robot_client.py` |
| `REDIS_HOST` | `redis` | Redis host for `mc.mapping.map_update` |
| `MAP_WIDTH` / `MAP_HEIGHT` | `200` / `200` | grid cells |
| `MAP_RESOLUTION` | `0.05` | meters/cell |
| `MAP_ORIGIN_X` / `MAP_ORIGIN_Y` | grid centered on (0,0) | world coords of cell (0,0) |
| `EXPLORE_FORWARD_SPEED` | `0.35` | m/s while exploring normally |
| `EXPLORE_SLOW_SPEED` | `0.12` | m/s while crossing a detected stair/ramp band |
| `EXPLORE_YAW_KP` | `1.4` | heading-correction gain |
| `EXPLORE_WAYPOINT_TOL_M` | `0.12` | meters, waypoint-reached tolerance |
| `EXPLORE_WAYPOINT_TIMEOUT_S` | `8.0` | seconds before a stuck leg is abandoned and replanned |
| `EXPLORE_TICK_S` | `0.1` | control loop period |

## Try it (against the mock backend, no physical robot needed)

```bash
cd mapping
ROBOT_BACKEND=mock python app.py
# in another shell:
curl -X POST http://localhost:9102/_debug/arm          # mock starts disarmed
curl -X POST http://localhost:9102/explore/start        # 409 if you skip the arm step
curl http://localhost:9102/explore/status
curl http://localhost:9102/map | head -c 300
curl -X POST http://localhost:9102/explore/stop
```

Via docker-compose (from the `mission-control/` root):

```bash
docker compose up --build mapping redis
curl -X POST http://localhost:9102/_debug/arm
curl -X POST http://localhost:9102/explore/start
```

## Known limitations / deliberate simplifications

- LiDAR points from `robot_client.get_lidar_points()` are treated as
  already being in world/map coordinates. `RobotClient`'s abstract
  docstring says "robot frame", but both `MockRobotClient` and
  `LiveRobotClient` (via the WebRTC bridge's `/lidar`) actually return
  points already offset by the robot's pose — matching that observed
  behavior was the pragmatic choice here.
- The mock robot's pose `z` and IMU pitch never move in a way that would
  realistically trigger `StairDetector` (pitch noise amplitude is only
  ~0.02 rad vs. the 0.12 rad threshold), so the multi-level path is
  implemented and unit-testable but cannot be exercised end-to-end
  against the mock — it will need real (or at least a beefed-up mock)
  IMU/pose data to validate against actual stairs.
- Exploration drives with a simple point-and-shoot heading corrector
  along a BFS grid path, not a smoothed/pure-pursuit trajectory — fine
  for a robot-vacuum-style wander, not meant to be a general motion
  controller (that's `navigation`'s job for goal-directed driving).
- `walls` uses a simple "max seen height bucket, never decays" update
  rule rather than a full probabilistic height model — adequate for
  distinguishing "nothing here" / "low obstacle" / "tall wall" without
  the complexity of a second log-odds filter.
