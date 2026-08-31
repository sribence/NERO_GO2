# webrtc_bridge

Kamera + LiDAR + telemetria hozzáférés a Go2-höz a **hivatalos** Unitree WebRTC protokollon keresztül ([unitree_webrtc_connect](https://github.com/legion1581/unitree_webrtc_connect), MIT) — ugyanaz, amit a mobilapp is használ, nem kell jailbreak.

**Ez a kód nagyrészt egy helyi LLM-mel (`qwen2.5-coder:14b`) generáltatva készült, kézi átnézéssel/javítással** — ld. [docs/13-lokalis-llm-delegalas.md](../../docs/13-lokalis-llm-delegalas.md) a workflow-ért.

## Státusz: NEM TESZTELVE ÉLŐ ROBOTON

A `RTC_TOPIC` kulcsnevek (`ULIDAR_ARRAY`, `LOWSTATE`, `SPORTMODESTATE`, `WIRELESS_CONTROLLER`) és a `data_channel_pubsub.subscribe()` metódus pontos szignatúrája **csak a könyvtár README-jéből lett kikövetkeztetve**, nem a tényleges forráskódból — a fizikai teszt előtt ez mindenképp ellenőrizendő/javítandó.

## Endpointok

| Endpoint | Mit ad |
|---|---|
| `GET /health` | `{"status": "ok", "connected": bool}` |
| `GET /camera.jpg` | legutóbbi kameraframe JPEG-ként, 404 amíg nincs |
| `GET /lidar` | legutóbbi LiDAR pontfelhő JSON-ban (max 5000 pontra ritkítva) |
| `GET /state` | legutóbbi lowstate + sportmodestate + távirányító adat |

## Firmware-verzió függő beállítás

Ha a robot firmware-je **≥ 1.1.15**, per-eszköz AES-128 kulcs kell (`UNITREE_AES_128_KEY` env var) — ezt a `unitree-fetch-aes-key` CLI-vel lehet lekérni (Unitree fiók login szükséges hozzá). Régebbi firmware-nél nem kell semmi extra.

## Egyszerre csak egy kliens

A robot csak **egy WebRTC-kliens** kapcsolatot enged egyszerre — ha közben a hivatalos mobilapp is csatlakozva van, ez a bridge `RobotBusyError`-t fog kapni.

## TODO (holnapra, robotnál)

- [ ] Firmware-verzió ellenőrzése a robotomon (kell-e AES-kulcs)
- [ ] `RTC_TOPIC` pontos kulcsnevek ellenőrzése a ténylegesen telepített library forrásában
- [ ] `data_channel_pubsub.subscribe()` API valós tesztelése
- [ ] Első élő kamera+LiDAR adat ellenőrzése
