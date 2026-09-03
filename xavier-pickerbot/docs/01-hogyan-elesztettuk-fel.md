# Hogyan élesztettük fel

A robot dobozból kikapcsolt, hálózat és időszinkron nélküli állapotban volt. Ez a napló azt a sorozatot írja le, ahogy egy hardveres LED-villogástól eljutottunk egy élő, kamerát/LiDAR-t/3D-t streamelő webes irányítópultig.

## 1. Bekapcsolás — az első buktató

USB-C kábelt dugtunk a Jetsonba, semmi nem történt, egy LED sem gyulladt ki. Kiderült: **a Xavier NX modul USB-C portja tisztán adatport**, nem tápbemenet. A modult csak a barrel jack (19V) vagy a robot saját battery-tápköre indítja el. Miután a robotot a saját akkujáról indítottuk, azonnal életre kelt.

## 2. Hálózatra kötés

A robot statikus IP-t (`192.168.0.100`) használt, nem kért DHCP-t — a router kliens-listáján nem jelent meg, ami elsőre "nem is fut" benyomást keltett. Direkt Ethernet-kábellel, a laptopon beállított `192.168.0.50/24` statikus címmel oldottuk meg a rálátást. Részletek: [00-hozzaferes.md](00-hozzaferes.md).

Útközben belefutottunk:
- `ping` időtúllépés érvényes ARP-bejegyzés mellett → elavult/cache-elt ARP volt, a gép ténylegesen nem volt fent még.
- `RTNETLINK answers: File exists` `dhclient` közben → már volt route/IP az interfészen, nem volt fatális.

## 3. Az 1970-es óra

Miután SSH-n bent voltunk, az `apt install` DNS- és cert-hibákkal állt le (`Temporary failure resolving`, `chain uses not yet valid certificate`). Az ok: **a robot órája 1970-re állt vissza** egy korábbi áramkimaradás után — nincs benne RTC-elem, vagy lemerült. Egyszeri kézi javítás:

```bash
sudo date -u -s "$(date -u +'%Y-%m-%d %H:%M:%S')"
sudo timedatectl set-ntp true
```

Ez viszont minden áramtalanítás után visszatért volna. **Végleges megoldás (2026-08-25 óta telepítve): a `fake-hwclock` csomag.** Óránként (`cron.hourly`) és minden tiszta leálláskor elmenti az aktuális időt, boot-kor — még a hálózat felállása előtt — azt tölti be 1970 helyett, utána az NTP pontosít, ha van net. Hirtelen áramkimaradásnál max. kb. 1 órás eltérés lehet, ami elég a cert-ellenőrzéshez. Nem kell többé kézzel dátumot állítani.

## 4. A befagyott csomagkezelő

`sudo apt install` közben `Could not get lock /var/lib/dpkg/lock-frontend` hibába futottunk. Az `aptd` (aptdaemon) daemon befagyva tartotta a zárat egy korábbi, hálózat-visszatérésre triggerelt automatikus frissítés-ellenőrzés után. Javítás: `sudo kill <aptd_pid>` (biztonságos, D-Bus újraindítja, ha kell) — **nem** a `packagekit` service, az egy másik, különálló daemon, amivel könnyű összekeverni.

## 5. Internet-útvonal a robotnak

`apt install` DNS-hibái (`Temporary failure resolving`) onnan jöttek, hogy a robotnak nem volt kiútja internet felé — a gateway mezője üresen vagy rosszul állt. Miután a gateway-t a laptop IP-jére (`192.168.0.50`) állítottuk, és a laptopon ICS-t kapcsoltunk be a Wi-Fi-ről az Ethernetre, a robot kapott internetet.

## 6. rosbridge + web_video_server telepítése

A webes irányítópulthoz szükséges infrastruktúra nem volt gyárilag telepítve:
- `ros-noetic-rosbridge-server` — WebSocket-híd a böngésző és a ROS-topikok között (`rosbridge_websocket`, 9090-es port)
- `web_video_server` — már a lemezen volt, csak nem futott alapból (8080-as port, MJPEG stream-ek)

## 7. A kameradriver első összeomlása — és a tanulság

Tesztelés közben egy `/camera/toggle_ir` service-hívás **lefagyasztotta a teljes `astra_camera` node-ot** (`glog FATAL: Check failed: stream_video_mode_.count(stream_index)`), és a fizikai USB-eszközt beragadt állapotban hagyta — sima `pkill` + relaunch nem hozta vissza. Kellett egy USB-szintű `USBDEVFS_RESET` ioctl a device fájlra, csak utána indult újra tisztán a driver. Ennek eredménye a mai szabály: **a generált/futtatott kód soha ne hívja élőben az IR-kapcsolót**, csak relaunch-csal, más konfiggal, ha valaha kell. Részletek és a pontos reset-parancs: [07-ismert-hibak.md](07-ismert-hibak.md).

## 8. Ami ebből lett

A fenti hibákon átvergődve épült fel a `scripts/start_feeds.sh` indítószkript és a `scripts/dashboard.html` élő irányítópult — ez az a pont, ahol a robot "csak egy hardver" státuszból "van rajta egy működő saját projektünk" státuszba lépett. Lásd: [05-sajat-projekt-iranyitopult.md](05-sajat-projekt-iranyitopult.md).
