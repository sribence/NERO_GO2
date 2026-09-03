# Saját projekt #1 — élő webes irányítópult

**Fut, tesztelve 2026-08-25-én.** Egyetlen oldal, minden élő szenzor-feed egy helyen, böngészőből: [scripts/dashboard.html](../scripts/dashboard.html).

## Mit tud

- **Két kamera élőben**, egy oldalon:
  - **Astra RGBD** → `/camera/rgb`, `/camera/depth`, (IR csak akkor, ha az RGB ki van kapcsolva — driver-korlát, egyszerre csak az egyik megy)
  - **Wheeltec C70** (a karra szerelt USB webkamera) → `/usb_cam/image_raw`
- **Kamera mód kapcsolók** (RGB/Depth be-ki) élő `std_srvs/SetBool` hívásokkal, relaunch nélkül a lapról.
- **Depth kép saját canvas-renderelése** — a `web_video_server` nem tudja a 16UC1 nyers mélységformátumot automatikusan színes képpé konvertálni (`cv_bridge` hiba: `[16UC1] is not a color format`), ezért ezt a lap saját JavaScript-je csinálja.
- **3D point cloud + LiDAR overlay**, Three.js + OrbitControls (kattints+húzd forgatáshoz, görgő zoomhoz) — `/camera/depth/points`-ból (kék), a LiDAR `/scan` ugyanabba a 3D térbe vetítve (narancssárga).

## Indítás

```bash
# a roboton, SSH-n át:
ssh -i ~/.ssh/pickerbot_mini wheeltec@192.168.0.100 'bash -s' < scripts/start_feeds.sh
```

Elindítja: `roscore`, Astra kamera, LiDAR, C70 usb_cam, `web_video_server`, `rosbridge_websocket`.

```bash
# helyben, a scripts/ mappában:
python -m http.server 8901
```

Majd nyisd meg: `http://127.0.0.1:8901/dashboard.html` — **fontos: ne `file://`-ként**, mert az statikus pillanatképként fut, a WebSocket-kapcsolat el sem indul.

Nyers kamera-lista debughoz: `http://192.168.0.100:8080/` (csak sima 8-bites RGB/C70 képekhez jó, a Depth itt `cv_bridge` hibát dob — azt a dashboard saját canvas-render-je oldja meg).

## Technikai buktatók, amiket ez a projekt oldott meg

1. **A rosbridge Base64-ként küldi a bájttömb mezőket.** A `PointCloud2.data` és `Image.data` string, nem JSON szám-tömb. `new Uint8Array(msg.data)` csendben 0 pontot ad — `atob()`-bal kell dekódolni.
2. **A LiDAR↔kamera transzformáció be van égetve a kódba**, nem élő TF-fel megy. A `ROSLIB.TFClient` a böngészőben csak a `/tf` topicot hallgatja; a robot statikus geometriája (URDF-ből) `/tf_static`-on megy, amit a kliens sosem kap meg. Fix mechanikai szerelésnél (LiDAR és kamera egymáshoz képest nem mozdul) egyszerűbb és megbízhatóbb a mért transzformációt egyszer lekérdezni (`rosrun tf tf_echo laser camera_depth_optical_frame`) és beégetni.
3. **Az IR kapcsoló szándékosan nincs bekötve a lapon** — lásd [07-ismert-hibak.md](07-ismert-hibak.md).

## Mit nem tud (még)

- Nem irányítja a motorokat vagy a kart — ez tisztán szenzor-megfigyelő irányítópult volt, az eredeti cél (motor/kar webes vezérlés) még nincs implementálva ezen a felületen.
- Az Astra RGB nem akart bekapcsolni egy vizsgálat közben — ez a hiba a session lezárásakor még nyitott volt, nem lett kivizsgálva.
