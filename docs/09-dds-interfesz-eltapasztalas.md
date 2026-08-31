# Ismert hiba: CycloneDDS interfész-eltérés (`eth0` vs `eth10`)

## A megfigyelés

A natív, gyári CycloneDDS config a Jetson dokkon (`~/cyclonedds_ws/cyclonedds.xml`, betöltve a `CYCLONEDDS_URI` környezeti változóval a `~/.bashrc`-ből):

```xml
<NetworkInterface name="eth0" priority="default" multicast="default" />
```

A géppel ténylegesen létező, aktív interfész neve viszont **`eth10`** (altname `enP8p1s0`) — `eth0` egyáltalán nem létezik ezen a rendszeren (ld. [01-halozat.md](01-halozat.md)).

## Valószínű magyarázat

A `.bash_history` alapján a korábbi tulajdonos/support kézzel piszkálta a hálózati interfész-elnevezést (`sudo cat /etc/udev/rules.d/70-persistent-net.rules`, kernel/DTB csere, reboot-ok). Valószínű, hogy az interfész eredetileg `eth0` néven jött létre, majd egy udev persistent-net szabály vagy egy kernel/DTB-csere miatt átnevezésre került `eth10`-re — a CycloneDDS config viszont nem lett frissítve ezzel összhangban.

## Következmény

Ha a CycloneDDS explicit egy nem létező interfészre próbál kötni, az SPDP (discovery) multicast valószínűleg **nem a várt interfészen** megy ki, vagy a discovery egyáltalán nem működik megbízhatóan a `rt/...` topicokhoz. Ez megmagyarázhatja, ha a natív ROS2-es DDS-alapú eszközök (pl. egy jövőbeli Foxglove-bridge) nem látnák rendesen a topicokat.

## Amit ez idáig NEM csináltunk

**Nem javítottuk ki a natív configot** — ez a [00-BIZTONSAGI-SZABALYOK.md](00-BIZTONSAGI-SZABALYOK.md) szabálya szerint rendszer-módosítás, ami explicit jóváhagyást és előtte mentést igényel. A jelenlegi működő gyári stack (pl. a mobilapp WebRTC-kapcsolata) lehet, hogy egyáltalán nem ezen a CycloneDDS-rétegen megy keresztül, tehát a hibás config **lehet, hogy soha nem okozott látható problémát** — ezt még nem teszteltük ki.

## Amit csináltunk

A [docker/dev/](../docker/dev/) fejlesztői konténerben egy **saját, helyesbített** `cyclonedds.container.xml` fájlt használunk (`eth10`-zel) — ez csak a konténeren belül érvényes, a natív fájlt nem érinti.

## TODO

- [ ] Leellenőrizni, hogy a natív `rt/...` DDS-topicok egyáltalán látszanak-e kívülről (pl. `ros2 topic list` a konténerből) a jelenlegi hibás configgal is — lehet, hogy a `multicast="default"` és az `AllowMulticast=spdp` beállítás miatt működik minden interfészen, és az `eth0` név csak egy figyelmen kívül hagyott, nem kritikus mező
- [ ] Ha tényleg gond van vele, és a natív stack ettől szenved: **javaslatot tenni** a userek felé a natív config javítására (mentéssel!), nem magunktól megcsinálni
