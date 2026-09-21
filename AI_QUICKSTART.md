# NERO GO2 — AI Quickstart

Első olvasmány bármilyen AI-nak (Claude, más chat, más eszköz), mielőtt a Go2
robot projekten dolgozik. Cél: 1 oldal, nem 100k token.

> Ha Claude Code-ban dolgozol: futtasd a `/caveman full`-t (tömör, technikai
> válaszstílus). Más AI eszközben ez a parancs nem létezik, hagyd ki.

## Modulok / repók

| Modul | GitHub | Helyi útvonal (ezen a gépen) | Mire való |
|---|---|---|---|
| Fő repó | `sribence/NERO_GO2` | `C:\Users\user\NERO_GO2` | submodule-ok összefogása, docker-compose, docs/, scratch/ |
| Brain & Autonomy | `sribence/go2-brain-logic` | `src/go2-brain-logic` | mission_control (FastAPI pillérek: mapping, navigation, orchestration, blackbox, audio, sensors, multicam), mc_motion (SportClient, remote-override, odom) |
| Hardware Bridge | `sribence/go2-hardware-bridge` | `src/go2-hardware-bridge` | webrtc_bridge (hivatalos Unitree WebRTC, audio hub), rtl8821cu_driver (wifi-dongle driver, 3rd party submodule: `morrownr/8821cu-20210916`) |
| GUI & Visualization | `sribence/go2-gui-visualization` | `src/go2-gui-visualization` | web_dashboard, go2-console (operátori konzol, saját repó is: `C:\dev\go2-console`) |
| Xavier Pickerbot | dokumentáció itt: `NERO_GO2/xavier-pickerbot/` | — | testvér-robot, **külön hálózat** (192.168.0.100), nem ugyanaz az alháló mint a Go2 |

Minden submodule `main` ágon, önálló git history. `git submodule status` a
fő repóban mutatja az aktuális pointereket — ha hibát dob
(`no submodule mapping found`), az `.gitmodules` hiányzik valamelyik szinten,
ld. javítási minta a `go2-hardware-bridge/.gitmodules`-ben.

## Robot elérés

- **Helyi Wi-Fi SSH:** `ssh go2` (`~/.ssh/config`: `Host go2 192.168.123.18`, user `unitree`)
- **Tailscale SSH (Erről a Windows gépről, tailnet tag):** `ssh go2-ts`
  - Alias a `~/.ssh/config`-ban `100.70.125.40`-re mutat, `id_ed25519_neonpc` kulccsal, jelszó/gateway nem kell.
- **Tailscale SSH (Másik gépről, nincs alias/kulcs):** `ssh unitree@100.70.125.40`
  - Feltétel: a gép tagja ugyanannak a tailnetnek (`dualis.fejlesztes.email@` fiók, meghívás/ACL kell). A Tailscale SSH identity-alapon beenged kulcs nélkül is, vagy jelszóval (`123`).
- **Gateway-en át (ha Tailscale nem elérhető):** `ssh go2-viagw`
- **Fedélzeti gép:** Jetson Orin, Ubuntu, IP: `192.168.123.18` (helyi Wi-Fi) / `100.70.125.40` (Tailscale)
- **Robot repó a roboton:** `~/NERO_GO2` (ugyanaz a submodule-struktúra, saját klón)
- **Pontos IP/port tábla:** [mission_control/CONVENTIONS.md](src/go2-brain-logic/mission_control/CONVENTIONS.md) — ez a mérvadó, ne máshonnan idézd.

## Push-módszer — FONTOS, sose térj el

Mind a négy repó **PUBLIC** a GitHubon. Roboton **sose tárolj git tokent**
lemezen (a robot saját biztonsági állapota gyenge — ld.
`mission_control/AUDIT-2026-09-10.md`).

- **Erről a Windows gépről** (itt, `C:\Users\user\NERO_GO2`): sima
  `git push` működik, a `gh` CLI már be van állítva credential helperként.
- **A robotról** (roboton futó `~/NERO_GO2` klónból): nincs tárolt hitelesítés,
  push csak relével, Windowsról indítva:
  ```bash
  TOKEN=$(gh auth token)
  ssh go2 "cd ~/NERO_GO2/<útvonal> && git push https://oauth2:${TOKEN}@github.com/sribence/<repo>.git <branch>"
  ```
  A token sosem íródik fájlba a roboton.

## Elavult dokumentáció — figyelem

`PROJECT_CONTEXT.md` a submodule-restrukturálás **előtti** állapotot írja le,
két (mára nem létező) klón összefésült, sérült leírásával
(`C:\dev\NERO_GO2` már nincs meg). Ne ebből dolgozz — ez a fájl a pontos,
jelenlegi állapot.
