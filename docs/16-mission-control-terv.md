# Mission Control — önálló side-quest modul

2026-09-10-én indult, a robot alap-infrastruktúrájára (DDS-kapcsolat, `webrtc_bridge`, a `web_dashboard` térképező/navigációs kezdeményei) építő, de önállóan fejlődő rendszer: autonóm padló+fal térképezés, kattints-a-térképre navigáció (lépcső-tudatos), multi-protokoll task-orchestration (WebSocket/MQTT/REST, várakozó lépés-lánc külső rendszerek API-jaira), on-demand szenzor-parancsok (fotó/LiDAR/hőkamera), multi-USB-kamera, esemény-vezérelt hang, "feketedoboz" naplózás, Tailscale távoli elérés, és egy induló Unity-szerű 3D digitális iker kezelőfelület.

Teljes architektúra, pillér-leírások, indítási útmutató, extra ötletlista és ismert korlátok: **[mission-control/README.md](../mission-control/README.md)**. Fejlesztői konvenciók (robot-kliens interfész, Redis event-bus csatornák, map JSON-séma, Dockerfile-minta): **[mission-control/CONVENTIONS.md](../mission-control/CONVENTIONS.md)**.

A meglévő `docker/web_dashboard`, `docker/webrtc_bridge`, `docker/mapping` és `docker/mock_robot` továbbra is a fő repó része és önmagában is működik (elsősorban a `/showcase` oktatási demóhoz) — a `mission-control/` ezekre a bevált mintákra épít, de külön, saját docker-compose stackként fejlődik tovább.
