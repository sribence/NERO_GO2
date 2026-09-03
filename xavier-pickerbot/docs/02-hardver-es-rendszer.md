# Hardver és rendszer

> Ez a leltár méréssel és a gépen végzett vizsgálattal készült, nem katalógusadat.

## A robot azonosítása

Wheeltec gyártmányú, "Xavier Pickerbot Mini" néven értékesített oktatási robot. **Fizikai konfiguráció: mecanum kerekes alváz + 4 tengelyű robotkar.**

A gyártó öt alváz-kar kombinációt telepített egy közös lemezképbe (`mini_mec_four_arm`, `mini_mec_six_arm`, `mini_4wd_four_arm`, `mini_4wd_six_arm`, `mini_tank_four_arm`), de **a mi példányunkhoz csak a `mini_mec_four_arm` és a `mini_mec_four_arm_moveit_config` releváns**. A többi package ott van a lemezen, de fejlesztéshez nem kell hozzájuk nyúlni, és nem szabad rájuk hivatkozni generált kódban.

A gyári konfiguráció valószínűsíthető rokona a nyilvánosan dokumentált **Wheeltec R550A** (Mecanum/Tracked + MoveIt karos) platformnak — a nálunk ténylegesen talált csomagok (lásd [../inventory.html](../inventory.html)) megegyeznek ezzel a mintázattal (LiDAR, IMU, kamera, MoveIt karkonfig).

## Fedélzeti számítógép

| | |
|---|---|
| Platform | NVIDIA Jetson Xavier NX (Tegra R35.6.1) |
| JetPack / L4T | 35.6.1 |
| OS | Ubuntu 20.04.6 LTS |
| ROS | Noetic (ROS 1, catkin) |
| Python | 3.8.10 |
| CUDA | 11.4 |
| Lemez | 233 GB, 83% tele — kb. 40 GB szabad |

**A `/timeshift` könyvtár egyedül 84 GB-ot foglal.** A szabad hely szűkös — nagy adathalmazokkal (tanítóadat, hosszú felvételek) ne számoljunk a robot saját lemezén, azok a Gateway/fejlesztőgép oldalára valók.

**ROS Noetic EOL.** A Jetson maradhat Noeticen, de újabb fejlesztésnél célszerű egy külön Agent-réteg mögé bújtatni, hogy a robot maga ne kelljen frissíteni ahhoz, hogy a rendszer többi része ROS2-re válthasson.

## Teljes vizuális szoftver-/tárhely-leltár

[inventory.html](../inventory.html) — funkció szerint csoportosított lista arról, mi foglalja a helyet és mi fut a lemezen.
