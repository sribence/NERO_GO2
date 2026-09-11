# NERO GO2 — 3D LiDAR SLAM Projekt Összefoglaló & Kalibrációs Jelentés

**Dátum**: 2026. szeptember 11.  
**Projekt**: NERO GO2 (Unitree Go2 Quadruped + Hesai PandarXT-16 3D LiDAR)  
**Tárhely / Repository**: `c:\Users\user\NERO_GO2`  

---

## 1. 🎯 Projekt Célja & Rendszerarchitektúra
A projekt fő célja a Unitree Go2 négylábú robot és a rá szerelt Hesai PandarXT-16 3D LiDAR szenzor adatainak egyesítésével egy tiszta, valós idejű 3D pontfelhő és 2D voxel térkép építése volt (ROS függőségek nélkül, tiszta C++/Python/WebGL alapon).

### Hardver & Szenzor Kalibráció:
- **LiDAR**: Hesai PandarXT-16 (16 csatornás 3D LiDAR, 360° FOV)
- **Robot Odometria**: Unitree Go2 IMU / Foot-Odometry JSON adatfolyam
- **Felfogatási Elforgatás (Extrinsic Yaw Offset)**: **$96.0^\circ$**
- **Gyro Skála Korrekció (IMU Drift Compensation)**: **$0.99\times$**

---

## 2. 🔑 Kulcsfontosságú Felfedezések & Áttörések

### A. Nyers Odometria Pontossága (A Felhasználó Kalibrációs Eredménye)
A felületen elvégzett interaktív mérések alapján kiderült, hogy a nyers odometria az alábbi két beállítással adja a legélesebb, elcsúszásmentes térképet:
1. **Gyro / Yaw Skála**: `0.99x` (1%-os korrekció az IMU szögsebességén)
2. **LiDAR-IMU Yaw Offset**: `96.0°` (A LiDAR fizikai elforgatása a robot tengelyéhez képest)

> **Eredmény**: Nyers Odometria módban (`ICP nélkül`) a szoba falai egyetlen tűéles, zárt téglalapként rajzolódnak ki, elforgatott duplikációk nélkül!

### B. Miért rontott a korábbi ICP / Scan Matching?
- A mesterséges Scan Matching és Pose Graph algoritmusok a falak ismétlődő mintázatai (geometriai szimmetriái) miatt téves lokális minimumokba húzták be a pozíciót.
- Mivel a nyers odometria $0.99\times$ skálázással és $96.0^\circ$ offsettel önmagában rendkívül stabil, a túlzott ICP algoritmusok deformációt és téves elforgatásokat vittek a térképbe.

---

## 3. 📂 Elkészült Modulok & Fájlok Jegyzéke

### 1. Interaktív Hangoló & Vizualizáció:
- `docker/mapping/generate_slam_workbench.py`: Interaktív WebGL SLAM generáló Python script.
- `slam_workbench.html` / `index.html`: 60 FPS Three.js interaktív felület csúszkákkal (Gyro skála, Offset, Idővonal).

### 2. Automatizált Kiértékelés:
- `docker/mapping/evaluate_slam_quality.py`: Automatizált SLAM minőségellenőrző (falkisugárzás RMS és voxel duplikáció számító).

### 3. Adatmozaik Mérések (JSONL):
- `docker/mapping/walk_kicsi.jsonl`: Kis szobai séta (60s, 478 képkocka)
- `docker/mapping/walk_seta1.jsonl`: Nagy séta (90s, 716 képkocka)
- `docker/mapping/walk_teszt.jsonl`: Álló robot teszt (60s, 717 képkocka)

### 4. Illesztő Script-ek:
- `docker/mapping/bounded_icp_slam.py`: Szigorúan korlátozott ICP Scan-to-Map motor.
- `docker/mapping/etalon_voxel_slam.py`: Pose Graph Loop Closure Keyframe Rebuild SLAM.

---

## 4. 📊 Optimális Paraméter Beállítások (Quick Reference)

| Paraméter | Optimális Érték | Leírás |
| :--- | :--- | :--- |
| **Algoritmus Mód** | `Nyers Korrigált Odometria` | Legtisztább falrajzolat, ICP nélkül |
| **Gyro / Yaw Skála** | **`0.99x`** | Megszünteti a kanyarok túlbordázását |
| **LiDAR-IMU Offset** | **`96.0°`** | Szobafalak ortogonális illesztése |
| **Voxel Rács** | **`2 cm` (vagy 5 cm)** | Részletgazdag 3D falmodell |
| **Pontmegtartás** | **`100%`** | 0% pont-törlés elve |

---

## 5. 🛠️ Mentési & Projekt Állapot
Minden módosítás, script, adatfájl és felület biztonságosan el van mentve a helyi Munkaterületen (`c:\Users\user\NERO_GO2`).

Egy git commit is létrehozható vagy áttekinthető a projekt jelenlegi állapotáról.
