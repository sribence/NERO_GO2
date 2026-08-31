# Lokális LLM-delegálás — hogyan generálódik a kód ebben a projektben

A NERO_GO2 fejlesztői munka egy részét **nem Claude írja kézzel**, hanem egy helyi, GPU-n futó Qwen2.5-Coder modell — Claude csak orchestrál (promptot ír, ellenőriz, javít, integrál). Ez tudatos döntés: a Claude API-tokenkeret szűkös, a helyi GPU-kapacitás viszont ingyenes és bőven van belőle.

## Infrastruktúra

- **Gép:** `localai` (Tailscale, `100.72.127.117`), RTX 5070 12GB VRAM
- **Modell:** `qwen2.5-coder:14b` — 9GB, teljesen befér a VRAM-ba (a nagyobb `qwen2.5-coder:32b` már nem férne be egyben, lassabb lenne)
- **Kapcsolódás:** [claude-sidekick](https://github.com/andrewbrereton/claude-sidekick) MCP-szerver, Claude Code `.mcp.json`-jába kötve (`ollama-sidekick` néven), `OLLAMA_BASE_URL=http://100.72.127.117:11434` env-változóval a `localai` gépre mutatva

## Miért nem MCP-szerver mindkét gépen

Csak **egy** gépen (ahol a Claude Code fut) kell az MCP-szerver — az maga egy vékony Node.js adapter, ami hálózaton keresztül hívja a `localai` gépen már futó Ollama-t. A `localai` gépen semmi extra telepítés nem kellett, ott már eleve élt az Ollama.

## Workflow egy konkrét feladatnál

1. Claude összeállít egy részletes, kontextusban gazdag promptot (a célkönyvtár API-ja, elvárt fájlstruktúra, konkrét követelmények)
2. Meghívja az `ollama_code_generation` (vagy `ollama_chat`) MCP-eszközt, `model: "qwen2.5-coder:14b"` paraméterrel — **ez a hívás nem terheli Claude tokenkeretét generálási költséggel**, a tényleges munka a helyi GPU-n történik
3. Claude **mindig átnézi és kijavítja** a kapott kódot, mielőtt bekerül a repóba — a modell hibázhat (ld. lentebb, konkrét példa)
4. A végleges, javított fájlok kerülnek a repóba, commit üzenetben jelölve, hogy melyik rész származik LLM-generálásból

## Model-erősség — reális elvárás

Benchmark-adatok (2026 eleji mérések): `Qwen2.5-Coder-14B` **89,6% HumanEval**, míg még a régebbi Claude 3.5 Sonnet is **93,7%**-ot ér el — a jelenlegi Sonnet 5 ennél is jobb. Tehát a helyi modell **nem egyenrangú helyettesítő**, hanem jól bevált, jól dokumentált, egyfájlos/scope-olt feladatokra ideális, **kötelező emberi/Claude-os átnézéssel**.

## Konkrét példa: `docker/webrtc_bridge/bridge.py` (2026-08-31)

A `qwen2.5-coder:14b` első generálása több hibát tartalmazott:
- a `conn` objektum csak lokális változó volt `main()`-ben, de a Flask `/health` route rálátott volna kívülről (`NameError` futáskor)
- az `asyncio.gather` a végtelen adatcsatorna-feliratkozásokkal blokkolta volna a videó-feldolgozó taszkot (soha nem futott volna le, mert a gather csak akkor tér vissza, ha MINDEN taszkja befejeződik — végtelen generátoroknál ez soha)
- hiányzó import-ok (`AesKeyRequiredError`, `RobotBusyError` használva, de nem importálva)
- a Dockerfile egy már nem létező Debian-csomagot (`libjasper-dev`) próbált telepíteni — ez elrontotta volna a build-et
- a `requirements.txt`-ben egy nem-létező pip-csomag (`portaudio` — ez rendszerkönyvtár, nem pip-csomag)

Mindezt Claude javította, mielőtt a fájlok bekerültek a repóba. Ez pontosan a várt munkamód — nem "vakon elfogadjuk", hanem generálás + kötelező review.
