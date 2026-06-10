# Arkitekturanalys — Prompt Team
*Datum: 2026-06-10 21:30 | HEAD: `eae0f48` | Branch: `main`*

---

## Arkitekturdiagram

```
Användare (Browser)
      │
      ▼
index.html (Vanilla JS, 4 784 rader)
  ├── Beställ-vy   → POST /api/submit
  ├── Att bygga-vy → POST /api/build-queue + SSE /api/builder/stream/{id}
  ├── Historik-vy  → GET /api/sessions
  └── Chatt-panel  → SSE /api/chat/{id}
      │
      ▼
FastAPI (app.py, 5 252 rader) — Railway (Python 3.x)
  ├── ThreadPoolExecutor (80 workers)
  ├── 7 globala threading.Lock
  ├── In-memory state:
  │     _backlog[], _build_queue[], _sessions{}, _chat_sessions{}
  │
  ├── Agent-system
  │     ├── SPECIALIST_AGENTS (array, ~30 agenter)
  │     ├── PRE_BUILD_AGENTS / POST_BUILD_AGENTS
  │     ├── run_agent() → Anthropic Claude API
  │     └── bash_exec, file_read, file_write, git_* (verktyg)
  │
  ├── Supabase (PostgreSQL REST)
  │     ├── backlog_items
  │     ├── build_queue_items
  │     └── Schema version: 3
  │
  └── GitHub
        ├── Webhook → POST /api/github/webhook
        ├── github_fetch() — fil-läsning i batchar (P3-Q)
        └── git push via subprocess (shell=True)
```

---

## Styrkor

**Robust lås-hantering**
7 dedikerade threading.Lock för kritiska sektioner (`_backlog_lock`, `_queue_lock`, `_sessions_lock`, `_chat_lock`, `_settings_lock`, `_or_client_lock`, `_projects_lock`). Race conditions som P1/P1-L/P1-O/P1-P är åtgärdade och godkända.

**SSE-streaming genomgående**
Alla långkörande operationer (builder, chat, review) streamar via Server-Sent Events. Användaren ser progress i realtid utan polling.

**Supabase-persistens implementerad**
`_sync_to_supabase_async()` skriver backlog och byggkö till Postgres i bakgrundstråd. Schema-versionscheck vid start (`SUPABASE_SCHEMA_VERSION = 3`).

**Säkerhetsagenter alltid-på**
`_ALWAYS_RUN_AGENT_IDS = {"hemlighetsvakten", "dataskyddsjuristen"}` körs alltid oavsett läge — bra defensivt mönster.

**WIP-limit**
Max 1 aktivt bygge per projekt enforced på flera nivåer (rad 40, 605, 772). Förhindrar parallella konflikterande byggen.

---

## Risker och förbättringsförslag

### Risk 1 — app.py trunkerad (KRITISK)
**Konsekvens:** Ny Railway-deploy misslyckas med SyntaxError. Servern körs bara för att Railway inte startat om processen sedan senaste lyckade deploy.
**Förslag:** Komplettera rad 5252 omedelbart. Precommit-hooken måste också verifiera att Python kan kompilera filen (`python3 -m py_compile`).

### Risk 2 — bash_exec utan begränsningar (HÖG)
**Konsekvens:** Agenter kan köra godtyckliga shell-kommandon i Railway-miljön, inklusive `rm -rf`, `curl` till externa endpoints, etc. En prompt injection-attack mot Claude API-svaret kan missbruka detta.
**Förslag:** Blocklista för destruktiva kommandon. Alternativt: lista av tillåtna kommandon (allowlist) i stället för blocklist.

### Risk 3 — delete_session() 861 rader (HÖG)
**Konsekvens:** Omöjligt att enhetstesta. Alla buggar i session-borttagning (lokal, Supabase, GitHub, filer) finns i en funktion utan tydliga gränser.
**Förslag:** Dela upp i 4–5 privata helpers, en per ansvarsområde.

### Risk 4 — In-memory state vid serveromstart (MEDIUM)
**Konsekvens:** `_backlog[]`, `_build_queue[]` och `_chat_sessions{}` lever bara i RAM. Railway kan starta om processen vid deploy, crash eller skalning. Supabase-synken är asynkron — data kan förloras i 100ms-fönstret.
**Förslag:** Läs alltid från Supabase vid start (redan delvis implementerat). Gör skrivningar synkrona för kritisk data (byggs-status).

### Risk 5 — 58 generiska except-block (MEDIUM)
**Konsekvens:** Programmeringsfel (AttributeError, KeyError) fångas och loggas som "mjuka fel". Buggar manifesterar sig som tysta felaktiga svar i stället för exceptions som syns i Railway-loggar.
**Förslag:** Specificera exception-typer. Låt oväntade undantag bubbla upp (eller logga som ERROR, inte WARNING).

### Risk 6 — index.html 4 784 rader (LÅG)
**Konsekvens:** Hela frontend i en fil — svårt att underhålla. Inline CSS och JS blandat med HTML.
**Förslag:** Framtida spår — dela upp i komponenter (t.ex. Vite + vanilla JS) när frontend-arbete intensifieras.

---

## Beroendekarta

| Beroende | Typ | Kritikalitet | Notering |
|----------|-----|-------------|---------|
| Anthropic Claude API | Extern | KRITISK | Alla agenter, chat, review |
| Supabase | Extern | HÖG | Persistent storage, schema v3 |
| Railway | Infrastruktur | KRITISK | Hosting, env vars (PORT, RAILWAY_ENVIRONMENT) |
| GitHub | Extern | HÖG | Webhook, filhämtning, push |
| httpx | Bibliotek | MEDIUM | Alla HTTP-anrop (Supabase, GitHub) |
| anthropic SDK | Bibliotek | KRITISK | Claude API-klient |
| FastAPI + uvicorn | Bibliotek | KRITISK | Web-framework |

---

## Förändring sedan föregående analys

Föregående analys baserades på `bfa1f45` (feat/agent-audit-export). Nu på `eae0f48` (main).
- app.py har vuxit från ~4 025 rader (föregående analys) till 5 252 rader (+30%)
- DRY-sprint1 påbörjad — R1 implementerad
- Supabase-persistens tillagd (var saknad i föregående analys)
- Ny trunkering på rad 5252 (nytt kritiskt fynd)
