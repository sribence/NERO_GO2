# mission-control

**Go2 "Mission Control"** — önálló, meglévő NERO_GO2-kódra épülő side-quest modul: autonóm padló+fal térképezés, kattints-a-térképre navigáció, multi-protokoll task-orchestration (WebSocket/MQTT/REST, várakozó lépés-lánc), on-demand szenzor-parancsok, multi-USB-kamera, esemény-vezérelt hang, "feketedoboz" naplózás, Tailscale távoli elérés, és egy induló Unity-szerű 3D digitális iker kezelőfelület.

A teljes tervet ld. `docs/16-mission-control-terv.md` a rep gyökerében. Ez a fájl a napi használati/fejlesztői referencia.

## Architektúra

```
mission-control/
├── core/            # egységes robot-kliens (mock|live), mindenki erre épül — port 9101
├── mapping/         # autonóm bolyongó térképezés, padló+fal réteg — port 9102
├── navigation/      # kattints-a-térképre A* navigáció — port 9103
├── orchestration/   # task-motor: goto → hívj API-t → várj → tovább; WS/MQTT/REST — port 9104
├── sensors/         # on-demand fotó / LiDAR-snapshot / hőkamera(stub) — port 9105
├── multicam/        # multi-USB-kamera élő nézet + mentés — port 9106
├── audio/           # esemény-vezérelt hanglejátszás — port 9107
├── blackbox/        # gördülő log+kamera-puffer, anomália → tartós mentés — port 9108
├── remote/          # Tailscale (Docker, userspace) + log-feltöltés
├── digital-twin/    # 3D operátori nézet (three.js), map+pose fogyasztó — port 9110
├── CONVENTIONS.md   # KÖTELEZŐ olvasmány minden pillér fejlesztéséhez
├── docker-compose.yml
└── mosquitto.conf
```

Lásd `CONVENTIONS.md`-t a pontos interfészekért (robot-kliens, Redis event-bus csatornák, map JSON-séma, Dockerfile-minta, log-formátum).

## Megnézni a felületet, robot és Docker nélkül (demó mód)

```bash
python demo.py
```

Egyetlen folyamat, szintetikus adatokkal, a **valódi** kezelőfelülettel (ugyanaz a
`digital-twin/static/`). Kiírja a localhost- és a LAN-címet is, tehát telefonról,
ugyanarról a WiFi-ről is megnyitható. Minden válasz `"demo": true`, amitől a fejlécben
DEMÓ jelvény világít. Nincs benne robot-kliens, DDS vagy WebRTC import — fizikai robotot
nem tud mozgatni.

Egy ~110 másodperces forgatókönyv végigviszi az összes UI-állapotot (közelség-riasztás,
vészfék, alacsony és kritikus akku), hogy ne kelljen kézzel előidézni őket. Részletek:
`AUDIT-2026-09-10.md` 8. fejezet.

## Indítás (robot nélkül, mock backenddel)

```bash
cd mission-control
docker compose up --build
```

Ez elindítja mind a 9 pillért + Redis + MQTT-t, `ROBOT_BACKEND=mock` alapértelmezéssel — semmi nem igényel élő robot-kapcsolatot.

Élesben, a Jetsonon:

```bash
ROBOT_BACKEND=live WEBRTC_BRIDGE_URL=http://192.168.123.18:8000 docker compose up --build
```

Tailscale csatlakoztatásához (csak ha van érvényes auth-key, ld. `remote/README.md`):

```bash
TS_AUTHKEY=tskey-... docker compose --profile remote up -d tailscale
```

## Gyors ellenőrzés

```bash
curl localhost:9101/state                                   # core: pose/battery/imu
curl -X POST localhost:9102/explore/start                    # mapping: bolyongás indítása
curl localhost:9102/map                                      # mapping: aktuális térkép
curl -X POST localhost:9103/goto -d '{"x":1,"y":1}' -H 'Content-Type: application/json'
curl -X POST localhost:9104/task -d '{"steps":[{"goto":[1,1]}]}' -H 'Content-Type: application/json'
curl -X POST localhost:9105/sensor/photo
curl localhost:9106/cameras
curl -X POST localhost:9107/audio/play/test
curl localhost:9108/buffer/status
open http://localhost:9110/                                  # digital-twin 3D nézet böngészőben
```

Minden pillér saját `README.md`-je (a mappájában) pontosabb, service-specifikus példákat ad.

## Extra fejlesztési ötletek (a jövőbeli mélyítéshez, priorizálatlan)

1. Akku/health előrejelzés + auto-hazatérés alacsony akkunál
2. Geofencing / virtuális tiltott zónák a térképen
3. Hang/szöveg-parancs híd helyi LLM-mel (Qwen2.5-Coder a `localai` gépen)
4. Ütemezett/ismétlődő őrjárat-útvonalak
5. Változás-detektálás két térképezési kör között ("mi mozdult el")
6. Multi-robot koordinációs horog (Xavier Pickerbot Mini bekapcsolása ugyanabba az orchestrationbe)
7. Web-es incidens-visszanéző UI a blackbox-hoz
8. Szimuláció/replay mód (rögzített blackbox-session visszajátszása)
9. Auth/hozzáférés-védelem az API/WS végpontokon Tailscale-en át

## Ismert, tudatosan halasztott korlátok

- `sensors/thermal` és `multicam` hőkamera-ága stub — nincs beszerzett hardver.
- `digital-twin` relokalizáció (ICP-alapú "hol vagyok" újra-megtalálás) egyelőre szimulált/fix konfidencia-értékkel — a valódi LiDAR-scan-match a `mapping` nyers scan-exportjától függ, később kötendő be.
- Tailscale-kapcsolat user auth-key-t igényel, nincs automatikusan bekapcsolva.
- Élő robotos végigtesztelés (Jetsonon, `ROBOT_BACKEND=live`) külön menetben esedékes. **Fontos pontosítás:** ez a scaffold kizárólag `ROBOT_BACKEND=mock` alatt lett ellenőrizve, és a mock épp azokat a kódutakat kerüli meg, ahol a valódi hibák voltak — ld. `AUDIT-2026-09-10.md`. A `live` út egyetlen sora sem futott még valódi roboton.
- Az élő telemetria-parszolás mezőnevei közül a `bms_state.soc` és az `imu_state.accelerometer` **ELLENŐRIZENDŐ** az első robotos menetben (`curl http://192.168.123.18:8000/state | jq keys`), MIELŐTT bármi mozgásparancsot élesítenél.
