# Hálózat

## Topológia

A robot belsejében egy Ethernet-switch köti össze a fedélzeti számítógépeket. A robot hátán/tetején lévő RJ45 csatlakozó **erre a belső switchre** csatlakozik — ha ide bedugsz egy laptopot kábellel, ugyanabban a `192.168.123.0/24` alhálózatban leszel, mint a robot vezérlőegységei.

| Eszköz | IP | Interfész | Szerep |
|---|---|---|---|
| Mozgásvezérlő board | `192.168.123.161` | — | alacsony szintű motor/szenzor vezérlés, natív DDS-en beszél, **nincs rajta webszerver** |
| Jetson dokk-számítógép | `192.168.123.18` | `eth10` (altname `enP8p1s0`) | fejlesztői/AI számítási egység, SSH-elérhető |
| Belső "gateway" | `192.168.123.1` | — | alapból nem válaszol (nincs rajta élő router alapállapotban) |
| Ajánlott host-PC | `192.168.123.99` (vagy más szabad cím) | — | a fejlesztői laptop |

A Jetsonon **csak `eth10` van** — nincs saját WiFi interfész ezen a boardon.

## Laptop csatlakoztatása (Windows)

1. Kösd be az Ethernet-kábelt a robot portjába és a géped hálózati kártyájába
2. IPv4 → manuális: IP `192.168.123.99`, maszk `255.255.255.0`, gateway üresen
3. Teszt: `ping 192.168.123.161`

PowerShell:
```powershell
New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.123.99 -PrefixLength 24
```

## SSH hozzáférés

```
ssh unitree@192.168.123.18
```
Jelszó: `123`

Windows alól, ha nincs interaktív SSH kliens kéznél nem-interaktív automatizáláshoz, PuTTY `plink.exe` használható jelszóval és pinnelt host-key-jel:
```powershell
plink.exe -ssh -pw 123 -hostkey "SHA256:b49bi+OYx/3BYWPsTlMZF1psSs5FW8FnpmFfHpfoDrk" unitree@192.168.123.18 "parancs"
```
(`-hostkey` nélkül a `plink` interaktívan vár a host-key jóváhagyására, ami nem-interaktív szkriptekben lefagyást okoz.)

A mozgásvezérlő board (`.161`) felé jelenleg **nem sikerült SSH-t nyitni** közvetlenül — több független forrás szerint bizonyos Go2-verziókon ez a board a dokk-számítógép nélkül nem érhető el közvetlenül.

## Portok a Jetson dokkon (`192.168.123.18`)

| Port | Szolgáltatás | Elérhető böngészőből? |
|---|---|---|
| 22 | SSH | nem |
| 80 | `unitree-upgrade` webes UI (Tornado, `/upgradePythonServer/server.py`) | **igen** |
| 111 | rpcbind | nem |
| 4000 | NoMachine (`nxd`) | nem (saját protokoll, kell hozzá a NoMachine kliens) |
| 7001, 12001, 23990, 23991 | NoMachine belső portok (csak localhost) | nem |
| 35773 | containerd (localhost) | nem |

Ld. részletesen: [06-webes-feluletek.md](06-webes-feluletek.md)

## Internet a robotnak

A robotnak alapból **nincs internete** ezen a belső hálózaton (a `.1`-es gateway nem válaszol). Ideiglenes megoldás internet-megosztással a laptopról — ld. [07-internet-megosztas.md](07-internet-megosztas.md).
