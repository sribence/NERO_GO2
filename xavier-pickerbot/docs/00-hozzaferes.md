# Hozzáférés — hálózat és SSH

## Gyors csatlakozás

```powershell
scripts\connect.ps1
```

Kulcsos, jelszó nélküli SSH-t használ. Sudo-hoz kell a jelszó: `dongguan`.

Ha a szkript nélkül, kézzel akarsz belépni:

```bash
ssh -i ~/.ssh/pickerbot_mini wheeltec@192.168.0.100
```

## Hálózati topológia — közvetlen kábel, router nélkül

A robotnak nincs saját internet-elérése és nincs a mi Wi-Fi hálózatunkon — közvetlen Ethernet-kábellel kötjük a fejlesztő laptophoz.

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

A robot Wi-Fi hotspotot is tud (alapértelmezett jelszó: `dongguan`), de nálunk a közvetlen Ethernet + statikus IP volt a megbízható megoldás.

## Kulcsos SSH beállítása (ha új robotpéldányhoz kell újra)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/pickerbot_mini -N "" -C "pickerbot-mini-robot"
# majd a publikus kulcsot fűzd hozzá a roboton: ~/.ssh/authorized_keys (jelszavas belépéssel egyszer)
```

## Amit ne csinálj

- **USB-C-ről nem indul be a Jetson.** A modul USB-C portja tisztán adatport, a bekapcsoláshoz a barrel jack (19V) vagy a robot saját battery-tápköre kell. Ha nem gyullad LED, nem is fog, amíg nincs tényleges tápfeszültség rajta.
- **ICS automatizálás PowerShellből (`HNetCfg.HNetShare` COM objektum) nem működött** ebben a környezetben (jogosultsági/interaktivitási korlát) — GUI-ból állítsd be, vagy maradj a statikus IP + közvetlen kábel megoldásnál.
- **Natív Windows OpenSSH kliens jelszavas authhoz nem működött** nálunk (`Permission denied (publickey,password)`), miközben ugyanaz a user/pass PuTTY `plink.exe`-vel azonnal működött. Ez most már nem számít, mert kulcsos belépésre álltunk át — de ha valaha jelszóval kellene visszamenni, `plink -pw`-t próbálj `ssh` helyett.
