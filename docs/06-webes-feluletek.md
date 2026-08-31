# Webes felületek

## `http://192.168.123.18/` — "unitree-upgrade"

Vue.js SPA, Tornado szerver szolgálja ki (`/upgradePythonServer/server.py`, `unitree-upgrade.service`, port 80). Címe: **"GO2 Extension Module Update"**.

Funkciók a felületen:
- Csomag feltöltés/telepítés (fájl-feltöltő mező)
- **"Factory Reset"** gomb
- **"Recover Last Version"** gomb
- Update Progress log-panel

⚠️ **KRITIKUS:** ez a felület **jelszó/bejelentkezés nélkül** elérhető bárkinek, aki fizikailag Ethernet-kapcsolatot létesít a robottal. A "Factory Reset" és "Recover Last Version" gombokra **véletlenül se kattintsunk** — visszaállíthatják/törölhetik a jelenlegi, gondosan felépített konfigurációt.

Ha bárki mást is rákötsz erre a hálózatra (pl. demózás céljából), tudatosítsd, hogy ide ne kattintgasson.

## `192.168.123.18:4000` — NoMachine

Távoli asztal szolgáltatás (`nxserver.service`, `nxd`, `nxnode.bin`). **Nem böngészőből** érhető el — saját bináris protokollt használ, ehhez a NoMachine kliens alkalmazás kell (letölthető: nomachine.com).

Ezzel a robot Jetsonjának **teljes grafikus asztalát** meg lehet nyitni és távolról vezérelni — hasznos lehet GUI-s eszközök (pl. RViz2) futtatásához közvetlenül a robotmegoldáson.

## A mozgásvezérlő board (`192.168.123.161`) felől

Nincs webszerver, nincs semmilyen HTTP port nyitva — csak a natív DDS-en kommunikál.
