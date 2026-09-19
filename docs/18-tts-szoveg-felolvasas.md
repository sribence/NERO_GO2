# Szöveg-felolvasás (TTS) — "a robot tud beszélni"

**Státusz (2026-09-17): offline TTS-modul + Flask végpont + unit tesztek
kész, ezen a gépen futtatva zöld. NINCS megerősített fizikai hangszóró a
roboton/dokkon — ld. lentebb "Hardver-készenlét" szakasz, ne áltassuk
magunkat.**

## Mi készült el

- [`docker/web_dashboard/speech.py`](../docker/web_dashboard/speech.py) —
  `speak_to_wav(text)` függvény, offline TTS-motorral (`pyttsx3`) WAV
  hangbájtokat generál. Hiányzó/hibás TTS-backend esetén `None`-t ad vissza
  és logol, **sosem dob kivételt tovább** — egy opcionális függőség
  hiánya nem dönthet le semmilyen route-ot.
- [`docker/web_dashboard/app.py`](../docker/web_dashboard/app.py) —
  `POST /api/speak` végpont (`{"text": "..."}` body, válasz: `audio/wav`
  vagy 503/400 hibakód).
- Ugyanitt: két meglévő akcióhoz (`wave`, `stand_up`) egy-egy kötött
  mondat van bekötve a `/run_action/<action_name>` route-ba
  (`_ACTION_PHRASES` dict) — háttérszálon, best-effort, egy TTS-hiba
  SOSEM befolyásolja az akció saját válaszát.
- [`docker/web_dashboard/tests/test_speech.py`](../docker/web_dashboard/tests/test_speech.py)
  — 11 unit teszt: `speak_to_wav` üres szövegre/hiányzó pyttsx3-ra/backend-
  hibára/sikeres szintézisre, `is_available()`, és a `/api/speak` route
  400/503/200 ágai. Mind mockolt TTS-motorral, valós hangmotor NÉLKÜL is
  lefutnak.
- [`docker/web_dashboard/requirements.txt`](../docker/web_dashboard/requirements.txt)
  — hozzáadva: `pyttsx3`.
- [`docker/web_dashboard/Dockerfile`](../docker/web_dashboard/Dockerfile) —
  hozzáadva: `espeak-ng` apt-csomag (Linux alatt a pyttsx3 natív backendje
  ezt igényli) + `COPY speech.py .`.

## Miért `pyttsx3` és miért WAV-bájtok a válaszban

- **Offline követelmény**: a feladat kizárta a felhős/fizetős API-t. A
  `pyttsx3` teljesen lokálisan szintetizál (Windows: SAPI5, Linux: espeak/
  espeak-ng, macOS: NSSpeechSynthesizer) — nincs hálózati hívás, nincs
  API-kulcs.
- **Miért nem "direkt lejátszás" a szerveren**: a `docker/web_dashboard`
  konténer Linux-alapú (`python:3.11-slim`), tipikusan headless — nincs
  megbízható audio-eszköz, amit a konténerből ki lehetne szólaltatni anélkül,
  hogy a hoszt audio-alrendszerét (ALSA/PulseAudio device passthrough)
  bekötnénk a Dockerbe. Ez ma nincs meg (ld. lentebb), és feltalálni/
  hazudni sem akartuk.
- **A választott megoldás**: a route WAV-bájtokat ad vissza, a böngésző
  (ami a dashboardot nézi) játssza le — ez a legegyszerűbb dolog, ami
  holnap minimális módosítással átvezethető egy valós, dokkra/Jetsonra
  kötött hangszóróra: a `speak_to_wav()` már most is tisztán a hangbájtokat
  adja vissza, csak a route-ban kellene "válasz a böngészőnek" helyett
  "írás egy ALSA/PulseAudio sink-be" ágat tenni — a TTS-motor és annak
  hibakezelése változatlan maradhat.

## Hardver-készenlét — EZ MÉG NYITOTT KÉRDÉS

**Nincs megerősítve, hogy a Go2 dokkon/Jetsonon van fizikai hangszóró,
amit ez a rendszer meg tudna szólaltatni.** Átnéztem a repót
(`app.py`, `docs/`) `speaker`/`hangszóró`/`audio`/`tts` kulcsszavakra:
az egyetlen találat a security-mód `_mock_play_audio()` függvénye
(`app.py`), ami eddig is csak egy log-sort írt ki
(`"[MOCK ACTION] hangfájl lejátszás: halt.mp3 (holnap: valós audio-hívás)"`)
— tehát ez a mai napig sem volt bekötve valós hardverre. Ez a TTS-modul
NEM old meg ezt a hiányt, csak a hang-*generálást* oldja meg offline
módon; a robotra/dokkra kötött *lejátszást* külön fel kell deríteni és meg
kell építeni (USB-hangkártya? a Jetson beépített audio-kimenete? a robot
saját, gyári hangszórója az Unitree SportClient valamelyik API-ján át? —
ezt még nem vizsgáltuk).

## Pontos függőség (telepítéshez)

```bash
pip install pyttsx3
```

Linux/Docker alatt **ez önmagában nem elég** — a pyttsx3 natív hangmotorja
espeak-et/espeak-ng-t hív, ami system-csomag, nem pip-csomag:

```bash
apt-get install -y espeak-ng
```

(A `Dockerfile` már tartalmazza mindkettőt — image-rebuild után nincs
extra lépés a konténerben. Windows fejlesztői gépen a `pyttsx3` a SAPI5-öt
használja, amit ez a rendszer eleve tartalmaz, tehát ott az `espeak-ng`
lépés nem kell.)

## Hogyan teszteld holnap reggel

1. **Unit tesztek** (nem kell robot, nem kell valós TTS-motor se, minden
   mockolt):
   ```bash
   cd docker/web_dashboard
   python -m pytest tests/test_speech.py -q
   ```
   Várt: `11 passed`.

2. **Valós szintézis, mock SDK móddal, robot nélkül**:
   ```bash
   cd docker/web_dashboard
   pip install pyttsx3   # + Linux esetén: apt-get install -y espeak-ng
   MOCK_SDK=1 python app.py
   ```
   Másik terminálból:
   ```bash
   curl -X POST http://localhost:5002/api/speak \
        -H "Content-Type: application/json" \
        -d '{"text": "Szia, én egy Go2 robot vagyok."}' \
        --output teszt.wav
   ```
   Ha 200 OK + egy lejátszható `teszt.wav` jön létre → a TTS-lánc működik
   ezen a gépen. Ha `503` jön → nézd meg a szerver logját, valószínűleg
   hiányzik az `espeak-ng` system-csomag (Linuxon) vagy a `pyttsx3` pip-
   csomag telepítése nem sikerült.

3. **Böngészős próba**: nyisd meg a dashboardot (`/`), és a böngésző
   konzoljában:
   ```js
   fetch('/api/speak', {method: 'POST', headers: {'Content-Type': 'application/json'},
     body: JSON.stringify({text: 'Szia!'})})
     .then(r => r.blob())
     .then(b => new Audio(URL.createObjectURL(b)).play());
   ```
   Ha hallod a böngésződ hangszóróján a felolvasást → a végpont működik.
   Ez **nem** a robot hangszóróján szól, ld. fenti "Hardver-készenlét".

4. **`wave`/`stand_up` akció-hook**: armed módban indítsd el a `wave`
   akciót a felületről (vagy `POST /run_action/wave`) — a szerver logjában
   meg kell jelennie a TTS-hívásnak (`speak_to_wav` hívás a háttérszálon).
   Mivel nincs böngésző-oldali automatikus lejátszás bekötve az akció-
   hookhoz (ez a lépés csak a jövőbeli hangszóró-útvonalat gyakorolja be,
   nem ad felhasználó felé hallható eredményt), ez ma este/reggel csak
   logban ellenőrizhető, nem hallható.
