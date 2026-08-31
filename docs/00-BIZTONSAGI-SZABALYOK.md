# Biztonsági szabályok — üzemeltetési alapelvek

## A helyzet

Ez a Unitree Go2 EDU példány egy **drága, nehezen pótolható konfigurációban** érkezett. Ha bármi elromlik rajta — akár egy rossz csomagfrissítés, egy törölt fájl, egy félresikerült rendszerbeállítás —, a helyreállítás (gyári reset, újratelepítés, gyártói support) **bonyolult és időigényes** procedúra.

A jelenlegi állapot a **natúr, működő, kész rendszer**. Ez az egyetlen ismert jó baseline. Ehhez úgy kell hozzáállni, mint egy tojáshéjhoz: ha eltörik, az nagy baj.

## Az alapszabály

> **A robot natív/gyári rendszerébe (Jetson dokk vagy mozgásvezérlő board) semmi új dolgot nem telepítünk közvetlenül.**
>
> Minden új funkció, eszköz, szolgáltatás kizárólag **Docker-konténerben**, szeparáltan kerülhet fel — úgy, hogy a meglévő rendszer (ROS Noetic+Foxy telepítés, `/unitree/` gyári modulok, `cyclonedds_ws`, netplan hálózati konfiguráció, systemd service-ek) egyáltalán nem sérül.

## Mit jelent ez a gyakorlatban

✅ **Szabad, nyugodtan:**
- Diagnosztikai/olvasó parancsok futtatása (státusz-lekérdezés, log-olvasás, `ps`, `ss`, `ip addr`, stb.)
- Fájlok **kimásolása** a robotról (biztonsági mentés céljából) — ez nem módosít semmit a robotom
- Ideiglenes, nem-permanens hálózati beállítások (pl. `ip route add` sudo-val, ami újraindításkor magától eltűnik és semmilyen konfigfájlt nem ír át)
- Docker-konténerek indítása/tesztelése, ha azok nem `--privileged` módban és nem host-hálózaton futnak feleslegesen

⚠️ **Csak explicit jóváhagyással, és előtte mentéssel:**
- Bármilyen `apt install`, `pip install` **rendszer-szinten** (nem konténerben)
- Fájlok írása/cseréje `/opt/ros`, `/unitree`, `/etc/netplan`, `/etc/systemd/system` alatt
- Systemd service-ek létrehozása, módosítása, engedélyezése/tiltása a hoszton
- Bármilyen "permanens" hálózati konfig-módosítás (netplan fájl írása)
- Firmware-frissítés, "Factory Reset", "Recover Last Version" (ld. [06-webes-feluletek.md](06-webes-feluletek.md))

❌ **Soha, kérés nélkül sem:**
- Törlés bármiből, ami nem általunk, ebben a session-ben létrehozott ideiglenes fájl
- A gyári `/unitree/` modulok, a natív ROS-telepítések, vagy a netplan konfig módosítása mentés nélkül

## Munkafolyamat kockázatos lépés előtt

1. **Kérdezz rá explicit megerősítésre** — ne feltételezz jóváhagyást
2. **Csinálj friss mentést** az érintett fájlokról/configról (ld. [backups/](../backups/))
3. Csak utána hajtsd végre a módosítást
4. Dokumentáld, mi történt (ez a repó pont erre való)

## Biztonsági mentés

A [backups/](../backups/) mappában eddig egy **konfiguráció-pillanatkép** van (2026-08-31): netplan, systemd service fájlok, `dpkg -l` csomaglista, hálózati/lemez állapot. Ez **nem teljes lemezkép** — ha egy teljes, visszaállítható klónra van szükség (pl. az SD-kártyáról/eMMC-ről/NVMe-ről `dd`-vel), az egy külön, tervezett, a robot fizikai leállításával járó művelet, amit még nem végeztünk el.

**TODO:** teljes lemezkép-mentés megtervezése és elvégzése, mielőtt bármilyen rendszer-szintű módosítást engedélyezünk a natív telepítésen.
