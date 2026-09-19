# mission-control — konvenciók minden pillérhez

Ezt minden pillér (mapping, navigation, orchestration, sensors, multicam,
audio, blackbox, remote, digital-twin) implementációjának be kell tartania,
hogy a `docker-compose.yml` egységesen tudja mindet összerakni.

## Robot-elérés

Soha ne hívj DDS-t vagy `webrtc_bridge`-et közvetlenül. Mindig:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
from robot_client import get_robot_client
robot = get_robot_client()  # ROBOT_BACKEND=mock|live env-től függ, default mock
```

A Dockerfile-ban a `core/` mindig bekerül `/app/core`-ba, a `PYTHONPATH`
tartalmazza — ld. lent a Dockerfile-mintát, ott már jó a sima
`from robot_client import get_robot_client` import, nincs szükség a fenti
`sys.path` trükkre a konténeren belül (csak akkor kell, ha valaki helyben,
konténer nélkül futtatja).

## Portok (fixek, ne ütközzenek)

| Pillér | Port |
|---|---|
| core (debug/status) | 9101 |
| mapping | 9102 |
| navigation | 9103 |
| orchestration | 9104 |
| sensors | 9105 |
| multicam | 9106 |
| audio | 9107 |
| blackbox | 9108 |
| digital-twin (static viewer) | 9110 |
| redis (event bus) | 6379 |
| remote (tailscale) | nincs saját HTTP port |

## Event bus (Redis pub/sub)

Egyszerű, meglévő infrastruktúra helyett nem drótozunk pontból-pontba.
Csatorna-elnevezés: `mc.<pillér>.<esemény>`, payload mindig JSON string.

```python
import redis, json, os
r = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=6379, decode_responses=True)
r.publish("mc.mapping.pose", json.dumps(pose.to_dict()))
# feliratkozás:
pubsub = r.pubsub()
pubsub.subscribe("mc.core.proximity_alert")
for msg in pubsub.listen():
    ...
```

Ismert csatornák (bővíthető):
- `mc.core.proximity_alert` — a security/proximity logika publikálja (ember túl közel), az `audio` pillér erre iratkozik fel
- `mc.mapping.map_update` — mapping publikálja map-változáskor, a `navigation` és `digital-twin` erre iratkozik fel
- `mc.core.anomaly` — bármelyik pillér publikálhat (akku, IMU-lökés, hő, folyamat-halál), a `blackbox` erre iratkozik fel és exportál
- `mc.orchestration.task_event` — task indul/lép/kész/hiba

## Fájlszerkezet pillérenként

```
<pillér>/
├── app.py            # belépési pont, FastAPI app, uvicorn a fenti porton
├── requirements.txt
├── Dockerfile
└── README.md          # mit csinál, milyen env-változói vannak, hogyan tesztelhető curl-lal
```

## Dockerfile-minta (minden pillérhez ugyanez, csak a port/mappanév változik)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY core/ /app/core/
COPY <pillér>/requirements.txt /app/<pillér>/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt -r /app/<pillér>/requirements.txt
COPY <pillér>/ /app/<pillér>/
ENV PYTHONPATH=/app/core:/app/<pillér>
WORKDIR /app/<pillér>
CMD ["python", "app.py"]
```

A `docker-compose.yml` build contextje mindig a `mission-control/` gyökér
(`context: .`, `dockerfile: <pillér>/Dockerfile`), hogy a `core/` elérhető
legyen build közben.

## Map-séma (padló+fal, a `mapping` pillér termeli, mindenki más ezt fogyasztja)

```json
{
  "resolution": 0.05,
  "origin_x": 0.0,
  "origin_y": 0.0,
  "width": 200,
  "height": 200,
  "level_id": "ground",
  "floor": [/* width*height, -1=ismeretlen, 0=szabad, 100=akadály, log-odds alapú */],
  "walls": [/* width*height, magasság-bucket 0-255, LiDAR z-szeletekből */]
}
```

## Log-formátum (a `blackbox` ezt gyűjti mindenkitől)

Minden pillér JSONL-t írjon a saját `/app/<pillér>/logs/events.jsonl`-jébe
(docker volume-ra kötve, ld. compose), soronként:
`{"t": <unix ts>, "pillar": "<név>", "level": "info|warn|error", "msg": "...", ...extra mezők}`

## Biztonság

Mozgásparancsot (`robot.move(...)`) csak akkor küldjön bármelyik pillér, ha
`robot.is_armed()` igaz — a `MockRobotClient`/`LiveRobotClient` ezt már
kikényszeríti, de a hívó kódnak explicit ellenőriznie kell és hibát kell
visszaadnia, ha nincs armelve, ne csendben nyeljen el semmit.
