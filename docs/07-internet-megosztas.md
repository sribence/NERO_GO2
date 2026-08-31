# Internet megosztása a robot felé (Windows laptopról)

A robot fedélzeti hálózatán (`192.168.123.0/24`) alapból **nincs internet** — a `.1`-es "gateway" cím nem válaszol. Ha a Jetson dokknak internet kell (pl. `apt install` egy Docker image build-hez, csomagfrissítéshez), ideiglenesen megoszthatjuk a laptop internetkapcsolatát.

⚠️ **Ez a beállítás szándékosan NEM permanens** — összhangban a [00-BIZTONSAGI-SZABALYOK.md](00-BIZTONSAGI-SZABALYOK.md) alapelvével, hogy a robot natív konfigját (netplan) nem írjuk át tartósan.

## Miért nem a szokásos ICS/NAT-recept

- A klasszikus Windows **Internet Connection Sharing (ICS)** alapból mindig `192.168.137.0/24`-re állítja a megosztott adaptert — ez ütközne a robot `192.168.123.x` hálózatával.
- A modern `New-NetNat` PowerShell cmdlet bizonyos Windows-gépeken **"Invalid class" (HRESULT 0x80041010)** hibával elszáll — ismert, makacs WMI-provider hiba, amit nem sikerült megoldani sem `winnat` szolgáltatás-indítással, sem egyéb módon.

## A működő megoldás: ICS regisztry-testreszabással

A Windows ICS alapértelmezett `192.168.137.0/24` tartománya registry-kulcsokkal átállítható a robot saját `192.168.123.0/24` hálózatára — így az ICS a `192.168.123.1` címet veszi fel a megosztott adapteren, ami **pont megegyezik** azzal, amit a Jetson netplan configja már eleve gateway-ként vár.

### 1. Registry (admin PowerShell)

```powershell
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters" -Name "ScopeAddress" -Value "192.168.123.0"
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters" -Name "ScopeAddressBackup" -Value "192.168.123.0"
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters" -Name "StandaloneDhcpAddress" -Value "192.168.123.1"
```

### 2. ICS bekapcsolása (GUI)

1. `ncpa.cpl` → Enter
2. Jobbklikk az **internetes** adapteren (pl. telefon USB-tethering) → Tulajdonságok → **Megosztás** fül
3. Pipa: *"Más hálózati felhasználók is csatlakozhassanak..."*
4. Legördülőben válaszd ki a **robot felé néző** adaptert
5. OK

**Megjegyzés:** ha a robot felé néző adapteren már van kézzel beállított statikus IP (pl. `192.168.123.99`), az ICS bekapcsolása **nem írja felül** — az adapter megtartja a saját statikus címét, csak a NAT/forwarding funkció aktiválódik mögötte.

### 3. Route a Jetsonon (ideiglenes, SSH-n keresztül)

Mivel a laptop nem feltétlenül veszi fel a `.1`-es címet (ha statikus IP van rajta), a Jetsonnak egy alacsonyabb metrikájú default route-ot kell adni a laptop tényleges címe felé — ez **nem ír netplan-fájlt**, csak a futó kernel route-tábláját módosítja, újraindításkor eltűnik:

```bash
sudo ip route add default via 192.168.123.<laptop-IP-je> dev eth10 metric 50
```

### 4. Ellenőrzés

```bash
ping -c 3 1.1.1.1        # nyers IP-szintű kapcsolat
ping -c 2 google.com     # DNS-feloldás
curl -s -o /dev/null -w '%{http_code}\n' https://github.com   # HTTPS
```

## Ismert érdekesség: rendszeróra

Amíg a robotnak sosem volt internete, a rendszerórája `1970-01-01`-en állt (nincs RTC-elem vagy sose kapott NTP-t). Mihelyt internet lett, a `systemd-timesyncd`/NTP **magától szinkronizálta** a helyes időre — ez azért fontos, mert téves rendszeridő HTTPS/TLS hibákat tud okozni (tanúsítvány-validáció).

## Ismert hiba: `packages.ros.org` SSL

A `packages.ros.org` cím SSL-tanúsítvány-hibát ad (`*.osuosl.org` cert nem egyezik a hostnévvel) — ez egy **elszigetelt, a mi hálózati beállításunktól független** CDN/mirror-probléma, nem gátolja az általános internet-hozzáférést (más HTTPS-oldalak, pl. github.com, hibátlanul mennek).

## Ha legközelebb megint kell internet

Az ICS beállítás (registry + GUI-kapcsoló) a laptopon **megmarad** újraindítás után is. Csak a robot oldali route-ot kell újra hozzáadni (3. lépés), mert az minden Jetson-reboot után elvész.
