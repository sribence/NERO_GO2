# NERO_GO2 Fejlesztési Szabályok

> Teljes kontextus, IP/port táblák, mission-control részletek: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). Roadmap: [TODO.md](TODO.md). Multi-agent/refaktor terv: [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md).

**Architektúra:**
- Backend: Flask (Python), Unitree SDK (Move() parancsok, négylábú robot)
- Frontend: Vanilla JS, HTML, SSE (Server-Sent Events) adatszórás. Nincs React/Vue.

**Kódolási Szabályok (Szigorú):**
1. Ne magyarázd túl a válaszokat.
2. Ha kódot módosítasz, CSAK a megváltozott részeket (diff) mutasd meg, soha ne generáld újra a teljes fájlt!
3. Tartsd tiszteletben a meglévő architektúrát, ne adj hozzá felesleges új könyvtárakat.
