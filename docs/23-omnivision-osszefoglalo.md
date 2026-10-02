# OmniVision 360 — tudás-összefoglaló (`feature/omnivision-360`)

Állapot: 2026-10-01. Ezt olvasd először, ha a branchen dolgozol. Részletek: [21 terv](21-omnivision-360-terv.md), [22 parancsolás](22-3d-parancsolas-otletek.md), `go2-brain-logic/mission_control/omni/CONTRACTS.md`, `mission/CONTRACT.md`.

**Hardveren még semmi nem futott.** Minden mock / szimulált módban készült és tesztelt.

---

## 1. Cél
Biztonsági szett a Go2-re: 360°-os látás, éjszakai felügyelet hőkamerával, ember keresése és **követése biztonságos távolságból (≥ 2.5 m, felülírhatatlan)**, emberkerülő autonóm felfedezés és térképezés, színes 3D-térkép, játékszerű 3D irányítás.

## 2. Hardver-rig
| cam_id | Eszköz | Hely | Bekötés |
|---|---|---|---|
| `rgb_front` / `rgb_left` / `rgb_right` / `rgb_rear` | USB webkamera, halszem / széles | elöl / oldalt / hátul | UVC MJPEG → `omni` |
| `th_front_narrow` | MLX90640-BAA (55°×35°), 32×24 | elöl | saját firmware (RP2040 / ESP32-S3), USB-serial → `thermal_bridge` :9120 (alternatíva: UVC hőkamera) |
| `th_front_wide` | MLX90640-BAB (110°×75°), 32×24 | elöl | ugyanaz az MCU, 2. I2C busz |
| `tof_rear` | Sipeed MaixSense A010 ToF, 100×100 | hátul | USB-CDC → `maixsense_bridge` :9121 |
| LiDAR | Hesai PandarXT-16 + Go2 L1 | tetején | meglévő |
| Számítás | Jetson Orin NX, JetPack 5.1.1, Python 3.8 | | |

## 3. Szolgáltatások és portok
| Szolgáltatás | Port | Repó | Feladat |
|---|---|---|---|
| `omni` | 9114 | brain-logic | kamerák, YOLO + hő 360, 3D követés, LiDAR-színezés, voxeltérkép, streamek |
| `safety_guard` | 9115 | brain-logic | **minden mozgás kapuja**: zónák, TTC, fail-safe, dead-man, sprint/ugrás-engedély |
| `mission` | 9116 | brain-logic | 3D misszió-végrehajtó (fejlesztés alatt) |
| `digital-twin` `/omni` | 9110 | brain-logic | OmniView 3D UI |
| `thermal_bridge` | 9120 | hardware-bridge | 2 hőkamera → °C-kép |
| `maixsense_bridge` | 9121 | hardware-bridge | A010 → mélységkép / pontfelhő |
| meglévők | 9101–9113 | | core, mapping, navigation, orchestration, sensors, multicam, audio, blackbox, fleet, perception, follow_executor |

Redis-csatornák: `mc.omni.persons`, `mc.omni.health`, `mc.omni.gesture`, `mc.safety.state`, `mc.mission.state` / `.event` / `.alert`.

## 4. Adatfolyam
```
USB RGB ×4 ─┐                     ┌─► YOLO (rektifikált hengeres nézet) ─┐
hő ×2 (9120)┼─► omni.capture ─────┼─► hő-folt detektor ──────────────────┼─► 3D (LiDAR > ToF > talajsík > méret)
ToF (9121) ─┘                     │                                      └─► MultiCamTracker (Kalman, gid) ─► mc.omni.persons
XT16 ───────────────────────────► colorize (z-buffer, RGB + °C) ─► (ember/test kiszűrve) ─► VoxelMap 5 cm ─► OVX1 WS
mc.omni.persons ─► safety_guard ◄── /move (mission, navigation, mapping, follow_executor, pursuit) ─► mc_motion
```

## 5. Kulcsdöntések (miért így)
| Döntés | Ok |
|---|---|
| A 360-varrást a **böngésző GPU-ja** végzi (bowl-shader) | a Jetson GPU-ja a YOLO-é |
| Egy GPU-folyamat (`omni`), a képkocka nem megy Redisen | nincs másolás, unified memory |
| Független `safety_guard`, minden mozgásforrás ezen át | a tervező hibázhat, a guard nem kerülhető meg |
| Követés ≥ 2.5 m, a guard nullázza a közelítést | „kergetés” utcán = sérülésveszély |
| Mozgó emberek nem kerülnek a voxeltérképbe | különben nyomot hagynak (mock: 16 790 → 54 voxel) |
| `PersonTrack.height_m` külön mező | a `z` a test középpontja; enélkül a gyerek-szabály (×1.5 zóna) minden felnőttre bekapcsolt |
| Sebesség a misszióban csak profil-név (`stealth/precise/normal/sprint`) | nyers m/s-t sem UI, sem LLM nem adhat |
| Sprint és ugrás csak **dead-man**-nel | elengedés = azonnali leállás |
| LLM-misszió mindig jóváhagyásra vár | a nyelvi modell nem mozgathat közvetlenül |

## 6. Safety-zónák (`safety_guard`)
| Szint | Feltétel | Hatás |
|---|---|---|
| STOP | ember < 0.8 m · TTC < 1 s · LiDAR < 0.5 m a menetirányban · LiDAR-adat nincs | csak forgás (és hátrálás, ha hátul szabad) |
| SLOW | ember < 2.0 m · TTC < 2 s · person-adat > 0.3 s régi | vmax 0.1–0.4 m/s |
| CAUTION | ember < 3.5 m | vmax 0.6 m/s |
| CLEAR | — | normál |
Gyerek (< 1.3 m) vagy gyors (> 2 m/s) ember → a távolságok ×1.5. A szint csak 0.5 s után enyhülhet (hiszterézis). A parancs csak csökkenhet, sosem nő.

## 7. Eszközök és protokollok
- **MLX90640 „MLXF” v1** (saját firmware → host): `"MLXF"`, ver, sensor_id, seq, millis, Ta, n=768, int16 centi-°C ×768, CRC16-CCITT. Fejlesztés alatt.
- **MaixSense A010:** csomag `00 FF` + len + 16 B metaadat + pixelek + checksum + `DD`; AT-parancsok (ISP, BINN, UNIT, FPS, DISP=2, COEFF?); mélység: UNIT=0 → (p/5.1)² mm. A Sipeed GitHub-forrásaiból, ellenőrzés folyamatban.
- **OVX1** (voxel-stream): `"OVX1"` + u32 version + u32 count + f32 res, majd count × (f32 x,y,z + u8 r,g,b,flags); flags bit0 = > 28 °C, bit1 = ember közelében.

## 8. Mérések (dev gépen / mock)
| Mi | Érték |
|---|---|
| omni pipeline, mock, 7 kamera | ~11 Hz |
| `project_base`, 30k pont | 1.4–1.9 ms (fisheye), 0.5–0.8 ms (pinhole) |
| colorize, 30k pont × 4 kamera | 9–16 ms |
| voxel integrate, 30k pont | 16–30 ms |
| Tesztek | brain-logic 254, hardware-bridge 36 — zöld |
Jetson-mérés még **nincs** (`BUD-4`).

## 9. UI (OmniView, `/omni`, `?demo=1`)
Bowl 360-nézet + Go2 URDF élő lábakkal; 5 nézet (orbit / chase / top / FPV / pontfelhő); színes voxelfelhő; ember-hologramok gid-del, távolsággal, sebességvektorral és predikcióval; safety-gyűrűk; HUD (7 kamera fps, safety, radar); éjszakai és hő-overlay; E-STOP (Space). Élő mock-backenddel tesztelve, 0 JS-hiba.

## 10. Fejlesztés alatt (6 + 2 agent)
| Agent | Mit |
|---|---|
| M1 | `mission` :9116 végrehajtó (goto, follow_path, jump_to, look_at, scan, action, say, shadow, watch, escort, patrol, explore, goto_label, return_home) |
| M2 | tervező: súlyozott A* (social + no-go), simítás, sebességprofil, ugrás-landolás, pure-pursuit |
| M3 | safety: dead-man, sprint-engedély, akció-kapu (ugrás), `mc_motion /capabilities /gait /speed_level` feature-flaggel |
| M4 | UI: kattints-és-menj + szellem-kutya, rajzolt pálya, waypoint-lánc, ugrás-mód, zónák, címkék, dead-man gomb, gamepad, NL-parancssor |
| M5 | zónák, címkék, home, esemény-szabályok, időzített járőr |
| M6 | természetes nyelv → misszió (Claude API, jóváhagyással), gesztus (int → odajön, tenyér → stop) |
| HW1 | MLX90640 firmware + `mlx90640_serial` driver + pty-s mock eszköz |
| HW2 | MaixSense: egyeztetés a Sipeed-repókkal, udev-szabály, golden tesztek |

## 11. Nyitott kérdések / kockázatok
1. Kalibráció (`CAL-1..6`) nélkül a színezés és a távolság csak becslés.
2. Jetson-terhelés mérése élesben, a meglévő `perception`-nel együtt.
3. 7 USB-eszköz → sávszél és tápellátás (2 USB-vezérlő, aktív hub).
4. Sprint: a Go2 firmware gyorsabb járásmódja (`SpeedLevel` / `SwitchGait`) ellenőrizendő; a `FrontJump` hossza mérendő.
5. Fizikai safety-protokoll (`SAF-9`) kötelező, mielőtt bármi autonóm módban mozog.
6. Utcai kamerás / hőkamerás megfigyelés: GDPR és helyi szabályok.
7. Az `mc_motion` default portja (9102) ütközik a `mapping`-gel — `MOTION_URL`-lel kell megadni.

## 12. Állapot lezáráskor (2026-10-02) — rate limit miatt félbemaradt munka
Kész + tesztelt + pusholva: omni, safety_guard (+ dead-man / sprint / akció-kapu / flotta-buborék), pursuit, nav_local, social layer, OmniView UI, mission tervező (M2), világ / szabályok / időzítő (M5), NL + gesztus (M6), thermal_bridge (UVC), maixsense_bridge (Sipeed-egyezés, golden tesztek, pty fake device). Tesztek: brain-logic 513, hw-bridge 62 zöld.

**WIP** (`wip:` commitok; szintaxis rendben, de NEM befejezett, NEM bekötött, NEM tesztelt):
| Modul | Fájlok | Hiányzik |
|---|---|---|
| M1 mission végrehajtó | `mission/executor.py`, `mission/schema.py` | `mission/app.py`, Dockerfile, tesztek, M2/M5/M6 bekötése, `request_passage`/`capture`/zóna-érték |
| R1 bizonyíték-rögzítő | `omni/recorder.py`, `omni/capture.py` (részben) | `/record`, `/incidents`, `/capture` route-ok, tesztek |
| F1 flotta | `fleet/registry.py`, `allocator.py`, `sync.py`, `app.py` (részben) | `/fleet` UI, tesztek, compose |
| M4 misszió-UI | `digital-twin/static/omni/mission*.js`, `gamepad.js` | bekötés `omni.js`/`omni.html`-be, validálás |
| M7 mobil UI | `digital-twin/static/omni/mobile/` | `omni_mobile.html`, `/m` route, PWA |
| HW1 MLX90640 | `thermal_bridge/firmware/`, `mlx90640_protocol.py`, `mock_scene.py` | soros driver, config, tesztek, fordítás |
| G1 gamepad | `gamepad_bridge/` (controller, devices, profiles) | szolgáltatás, tesztek, README |

Következő session: a fenti WIP-ek befejezése modulonként (a szerződések: `omni/CONTRACTS.md`, `mission/CONTRACT.md` §9), utána compose (`mission` :9116, `gamepad_bridge` :9122), majd Jetson-mérés.
Új ötletek (későbbi TODO): [24-halado-erzekeles-todo.md](24-halado-erzekeles-todo.md).
