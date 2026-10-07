# 26 — Hátmodul ("backpack") terv

Állapot: koncepció, 2026-10-04. Ág: `feature/omnivision-360`.

## Cél

Egy közös, védett, jól kinéző ház a Go2 hátán, a beépített Orin dokk fölött.
Befogadja az új perifériákat, és gondoskodik a tápellátásukról:

- HDMI kijelző (fejmodul, ld. `projects/go2-display-mod/` v13)
- RGB LED és reflektor (fejmodul lámpa + hátmodul)
- új kamerák (OmniVision 360: 4 kamera), RealSense D435i
- hőkamerák (MLX90640 board, 2×), IR kamera, A010 ToF
- mikrofon, hangszóró

## Kiinduló interfészek (beépített Orin dokk)

| Csatlakozó | Darab | Megjegyzés |
|---|---|---|
| USB-C | 2 | az egyik valószínűleg "full-function" (DP Alt Mode) — ellenőrizni |
| USB-A | 1 | USB 3.x? — ellenőrizni |
| RJ45 | 1 | GbE |
| M8 | 1 | Hesai XT16 (Ethernet + táp) — foglalt |
| XT30 | 1 | közvetlen akkufeszültség (8S Li-ion, ~25–33,6 V); terhelhetőség ismeretlen |

Ellenőrzés a roboton:

```bash
lsusb -t            # melyik port melyik root hubon / vezérlőn van
cat /sys/class/drm/*/status   # van-e DP kimenet az USB-C-n
```

## Architektúra-elv

**Saját NYÁK csak a táphoz és a vezérléshez. A nagysebességű jelek (USB3,
HDMI/DP, Ethernet) kész modulokon mennek.** A saját lapon nincs USB3/HDMI
layout-kockázat.

## Port-kiosztás (javaslat)

| Dokk port | Ide kerül | Indok |
|---|---|---|
| USB-C #1 (DP Alt) | USB-C dokk/hub: DP→HDMI a kijelzőre + **USB 2.0** eszközök: MCU, 2× MLX, A010, mikrofon, USB DAC | 4-sávos DP Alt módban a hub adatág tipikusan csak USB 2.0 — a lassú eszközöknek ez elég |
| USB-C #2 | USB3 hub (port-szintű tápkapcsolással, `uhubctl`) → 4× OmniVision kamera (MJPEG) | külön upstream a nagy sávszélességnek |
| USB-A | RealSense D435i közvetlenül | depth+RGB egy saját USB3 linket kér |
| RJ45 | 5-portos GbE switch modul (12 V) | tartalék: IP-kamera, RPi, laptop-szerviz port |

Nyitott: ha a két USB-C ugyanazon a vezérlőn van (`lsusb -t`), a kamerákat
újra kell osztani.

## Táplap (saját NYÁK)

1. **Bemenet XT30-ról:** biztosíték → fordított polaritás elleni ideális dióda
   → TVS (lábmotor-regen tüskék) → inrush-korlátos eFuse (pl. TPS2663, 60 V).
2. **5 V / 8–10 A buck:** USB hubok VBUS-a, kamerák, mikrofon, MCU.
3. **12 V / 4–5 A buck:** kijelző-driver, class-D erősítő, GbE switch, ventilátor.
4. **Reflektor:** külön konstans áramú LED-driver, PWM-dimmelés.
5. **Csatornánkénti load switch + árammérés (INA3221):** minden periféria
   külön kapcsolható. Hardveres power-cycle a RealSense / kamera
   lefagyásokra (ma ez csak szoftveres `camera_recovery.py`).
6. **MCU (STM32G0B1, mint a hőkamera-boardon):** USB CDC a Jetson felé.
   WS2812 (szintillesztővel), reflektor PWM, ventilátor PWM+tach,
   hőmérők, tápcsatornák, akkufeszültség-mérés.
7. **XT60 kimenet a fejmodulra** (a v9–v13 dokk/lámpa interfész már XT60-at vár).

## Teljesítménybüdzsé (becslés, ellenőrizendő)

| Eszköz | Sín | Tipikus W | Csúcs W |
|---|---|---|---|
| 7" kijelző + driver | 12 V | 3 | 5 |
| RGB LED (szoftveres limit) | 5 V | 3 | 10 |
| Reflektor 2× | CC | 10 | 20 |
| 4× OmniVision kamera | 5 V | 4 | 6 |
| RealSense D435i | 5 V | 2 | 3,5 |
| 2× MLX + A010 + IR kamera | 5 V | 2 | 3 |
| Mikrofon + USB DAC | 5 V | 1 | 1,5 |
| Class-D erősítő + hangszóró | 12 V | 2 | 10 |
| GbE switch | 12 V | 2 | 3 |
| Ventilátor, MCU, hubok | 5/12 V | 3 | 4 |
| **Összesen** | | **~32** | **~66** |

66 W / 25 V ≈ 2,7 A az XT30-on, a buck-hatásfokkal kb. 3 A.

## Ház

- XT16 és L1 látómezeje szabadon (fő geometriai korlát).
- Cél tömeg < 2–3 kg, alacsony súlypont.
- Aktív hűtés: szűrt bemenet, kimenet hátra.
- Panelre szerelt csatlakozók: szenzorokhoz GX12/M8, USB-hez csavaros rögzítésű
  változat (rezgés).
- Rezgéscsillapított rögzítés a dokk fölé; a dokk portjai rövid, rögzített
  kábelekkel jönnek fel.

## Nyitott kérdések

- [ ] XT30 terhelhetősége (Unitree doksi vagy mérés)
- [ ] `lsusb -t` a roboton: USB-C #1/#2 és USB-A vezérlő-kiosztása, DP Alt megléte
- [ ] XT16 pontos helye és látómezeje a háton
- [ ] Rögzítési pontok a háton (hasonlóan a fej 4× M3 dokk-furataihoz)
