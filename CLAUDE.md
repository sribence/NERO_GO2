# NERO_GO2 Fejlesztési Szabályok

> **ELSŐKÉNT olvasd:** [AI_QUICKSTART.md](AI_QUICKSTART.md) — modulok, repók, robot-elérés, push-módszer. 1 oldal.
>
> Roadmap: [TODO.md](TODO.md). Multi-agent/refaktor terv: [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md).
> `PROJECT_CONTEXT.md` ELAVULT (submodule-restrukturálás előtti, sérült tartalom) — ne onnan dolgozz.

**Architektúra:**
- Backend: Flask (Python), Unitree SDK (Move() parancsok, négylábú robot)
- Frontend: Vanilla JS, HTML, SSE (Server-Sent Events) adatszórás. Nincs React/Vue.

**Kódolási Szabályok (Szigorú):**
1. Ne magyarázd túl a válaszokat.
2. Ha kódot módosítasz, CSAK a megváltozott részeket (diff) mutasd meg, soha ne generáld újra a teljes fájlt!
3. Tartsd tiszteletben a meglévő architektúrát, ne adj hozzá felesleges új könyvtárakat.
