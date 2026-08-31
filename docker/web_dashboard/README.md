# web_dashboard

A NERO_GO2 fő webes vezérlőpultja — élő kamera (a `webrtc_bridge`-ből proxyolva), telemetria, virtuális joystick, akció-gombok (állj fel, feküdj le, ülj, integess, szív).

Architektúra-minta ([go2_dashboard](https://github.com/bentheperson1/go2_dashboard) by bentheperson1, MIT) alapján, de **nem másolat** — friss implementáció, két külön szolgáltatásra bontva:

- **`webrtc_bridge`** (5001-es port) — kamera/LiDAR/health, a hivatalos WebRTC-protokollon
- **`web_dashboard`** (ez, 5002-es port) — webes UI + mozgásvezérlés, natív DDS-en (`unitree_sdk2py`) keresztül

**Miért két szolgáltatás:** a robot csak **egy** WebRTC-klienst enged egyszerre. Ha a `web_dashboard` is saját WebRTC-kapcsolatot nyitna (mint az eredeti go2_dashboard), az ütközne a `webrtc_bridge`-vel. A mozgásvezérlés natív CycloneDDS-en megy, ami teljesen külön csatorna — nem ütközik semmivel.

## ⚠️ Biztonsági "arm/disarm" mechanizmus

A mozgásvezérlés (joystick, akció-gombok) **alapból zárolva van** (`armed=False`). A felhasználónak explicit fel kell oldania ("Vezérlés zárolva" gombra kattintva), és **30 másodperc inaktivitás után automatikusan visszazáródik**. Ez szándékos — ld. [00-BIZTONSAGI-SZABALYOK.md](../../docs/00-BIZTONSAGI-SZABALYOK.md), a robot drága, véletlen mozgásparancs nem mehet ki felügyelet nélkül.

## Státusz: NEM TESZTELVE, hiányos függőség

Ez a modul **helyi LLM-mel (qwen2.5-coder:14b) generált első verzióból lett átdolgozva** — az eredeti generálás több súlyos hibát tartalmazott (működésképtelen joystick-frontend, hibás változó-scope, kitalált SDK-metódus). A jelenlegi verzió kézzel javítva/újraírva. Részletek: [docs/13-lokalis-llm-delegalas.md](../../docs/13-lokalis-llm-delegalas.md).

**Nyitott függőségi probléma:** az `unitree_sdk2py` nem sima PyPI-csomag — az eredeti go2_dashboard repóban vendorolva van, forrása a [legion1581/go2_python_sdk2](https://github.com/legion1581/go2_python_sdk2) fork. Ezt a Dockerfile jelenleg **nem oldja meg** — holnap el kell dönteni: vendoreljük mi is, vagy `pip install git+...`-tel telepítjük.

## TODO (holnapra, robotnál)

- [ ] `unitree_sdk2py` telepítési módjának eldöntése és Dockerfile-ba illesztése
- [ ] Robot sorozatszámának (`UNITREE_ROBOT_SN`) beállítása
- [ ] Élő teszt: DDS-kapcsolat, telemetria, arm/disarm, joystick, akció-gombok — **óvatosan, biztonsági távolságból**
- [ ] `webrtc_bridge`-vel együtt tesztelve (mindkettő fusson egyszerre, host networkön)
