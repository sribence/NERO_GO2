# Hozzáférés — hálózat és SSH

## Gyors csatlakozás

```powershell
scripts\connect.ps1
```

Kulcsos, jelszó nélküli SSH-t használ. Sudo-hoz kell a jelszó: `dongguan`.

Ha a szkript nélkül, kézzel akarsz belépni:

```bash
ssh -i ~/.ssh/pickerbot_mini wheeltec@192.168.123.50
```

**2026-09-18 óta a robot a közös robot-hálón van (`192.168.123.50`)** — gateway PC + TP-Link router, internettel. A teljes leírás: [09-robot-halozat.md](09-robot-halozat.md). Az alábbi közvetlen kábeles módszer csak tartalék, ha a robot-háló nem elérhető.

## Tartalék: közvetlen kábel, router nélkül (régi módszer)

> ⚠️ Az alábbi címek (`192.168.0.100` az `eth0`-n) a 2026-09-18 előtti állapotot írják le. Most az `eth0` címe `192.168.123.50`: közvetlen kábellel a laptopra `192.168.123.99/24`-et állíts, és a robotot `192.168.123.50`-en éred el. **Ne tedd vissza** az `eth0`-t `192.168.0.100`-ra, mert akkor a hotspot DHCP-je kiszivárog a kábelre (lásd [09-robot-halozat.md](09-robot-halozat.md)).

A robotnak eredetileg nem volt saját internet-elérése — közvetlen Ethernet-kábellel kötöttük a fejlesztő laptophoz.

1. Laptop LAN-portja ↔ robot Ethernet-portja, kábellel.
2. A roboton **fix (statikus) IP**: `192.168.0.100`, netmask `255.255.255.0`.
   - **A gateway mező NEM mindegy!** Állítsd `192.168.0.50`-re (a laptop Ethernet-címére) — enélkül a robotnak nincs kiútja internet felé, csak a laptopig lát el.
     ```bash
     nmcli connection modify "Profile 1" ipv4.gateway 192.168.0.50 ipv4.dns "8.8.8.8 1.1.1.1"
     ```
     majd `connection down`/`up` — **óvatosan**, mert ezen az interfészen vagyunk bent SSH-val, rossz sorrendben kizárhatod magad.
3. A laptopon a megfelelő Ethernet-adapterre static IP kell, ugyanabba a subnetbe (admin PowerShellből):
   ```powershell
   New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.0.50 -PrefixLength 24
   ```
4. **Internet a robotnak:** Windows ICS (Internet Connection Sharing) a Wi-Fi-ről az Ethernetre megosztva (`ncpa.cpl` → Wi-Fi → Tulajdonságok → Megosztás fül → "Engedélyezés..." → cél: Ethernet). Ez NEM írja felül a kézzel beállított `192.168.0.50/24` címet, csak NAT-ol a robot felé — de a robot gateway-ét kézzel át kell írni rá (2. pont).

A robot Wi-Fi hotspotot is tud (SSID `WHEELTEC_OrinSuper_Noetic_JP515`, jelszó: `dongguan`, robot címe ott `192.168.0.100`) — SSH-ra jó, de a ROS master már a `192.168.123.50`-es címre van kötve.

## Kulcsos SSH beállítása (ha új robotpéldányhoz kell újra)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/pickerbot_mini -N "" -C "pickerbot-mini-robot"
# majd a publikus kulcsot fűzd hozzá a roboton: ~/.ssh/authorized_keys (jelszavas belépéssel egyszer)
```

## Amit ne csinálj

- **USB-C-ről nem indul be a Jetson.** A modul USB-C portja tisztán adatport, a bekapcsoláshoz a barrel jack (19V) vagy a robot saját battery-tápköre kell. Ha nem gyullad LED, nem is fog, amíg nincs tényleges tápfeszültség rajta.
- **ICS automatizálás PowerShellből (`HNetCfg.HNetShare` COM objektum) nem működött** ebben a környezetben (jogosultsági/interaktivitási korlát) — GUI-ból állítsd be, vagy maradj a statikus IP + közvetlen kábel megoldásnál.
- **Natív Windows OpenSSH kliens jelszavas authhoz nem működött** nálunk (`Permission denied (publickey,password)`), miközben ugyanaz a user/pass PuTTY `plink.exe`-vel azonnal működött. Ez most már nem számít, mert kulcsos belépésre álltunk át — de ha valaha jelszóval kellene visszamenni, `plink -pw`-t próbálj `ssh` helyett.
