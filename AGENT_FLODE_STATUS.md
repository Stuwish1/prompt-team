# AGENT_FLÖDE_STATUS.md
*Iteration 9 — ärendeflödesanalys av index.html (lokal version, 4121 rader)*  
*Skapad: 2026-06-10. Läs BUILD_TASKS.md för konkreta åtgärder.*

---

## Översikt — det fullständiga flödet

```
[1] LÄGE          Välj ny_funktion / granska_kod / buggrapport
      ↓
[2] GRANSKA       runReview() → POST /api/review
      ↓                         (defer_backlog: true, run_id, screenshots)
[3] PROGRESS      startProgressPolling() → GET /api/progress/{runId}  (1500 ms)
      ↓           recoverRunResult()     → GET /api/review/result/{runId}  (nätdöd)
[4] RESULTAT      renderResults() → kravBox, agentGrid, spec (dual view)
      ↓
[5] URVAL         sendSelectedFynd() → POST /api/backlog/add  ← LOKAL ENDPOINT
      ↓
[6] PLANERA       planBacklog()      → POST /api/backlog/plan ← LOKAL ENDPOINT
      ↓
[7] ATT BYGGA     loadAttBygga()     → GET /api/backlog + GET /api/build-queue
      ↓
[8] BYGGE         startBuild()       → POST /api/build-queue/{id}/send
      ↓           [MANUELL KLIPPBORD → paste i IDE → bygg → kopiera tillbaka]
[9] GRANSKA BYGGE kontrolleraBuild() → POST /api/build-queue/{id}/review
      ↓           alternativt: openBuildResult() → submitBuildResult() (paste-modal)
[10] GODKÄNN/OM   Godkänd: status → klar
                  Underkänd: ny prompt → status → behover_dig → blockerar kön
```

---

## Steg-för-steg — identifierade problem och status

### [1] Lägesval
| Status | Observation |
|--------|-------------|
| ✅ Fungerar | Tre lägen: ny_funktion, granska_kod, buggrapport |
| ⚠️ Gap | Mode sparas inte per projekt — byter man projekt byts inte läge om |

---

### [2] POST /api/review
| Status | Observation |
|--------|-------------|
| ✅ Fungerar | `defer_backlog: true` returnerar fynd utan att spara direkt |
| ✅ Fungerar | `run_id` genereras i fronten — recovery fungerar |
| ⚠️ Saknas | `spec_markdown` saknar storleksbegränsning — kan orsaka 413/timeout (se P1-M) |
| ⚠️ Saknas | Tom `project_id` accepteras av backend utan validering (se P1-N) |
| 🐛 Bug | Screenshots-bilagor skickas som base64 i JSON — ingen storleksbegränsning i UI |

---

### [3] Progress-polling
| Status | Observation |
|--------|-------------|
| ✅ Fungerar | 1500 ms polling, visar agent-för-agent-progress |
| ✅ Fungerar | `recoverRunResult()` pollar i 12 min om anslutningen bryts |
| 🐛 Bug | `_progress_set()` kör O(n) GC-loop under lock vid **varje** anrop — 75+ anrop per session (se P3-T) |
| ⚠️ Risk | Vid 5+ parallella sessioner hamnar GC-loopen i kritisk väg hela tiden |

---

### [4] Resultatrendering
| Status | Observation |
|--------|-------------|
| ✅ Fungerar | kravBox, agentGrid, spec (raw/preview), urvalssteget |
| ✅ Fungerar | Dual view för spec (markdown preview / rå text) |
| ⚠️ UX | Agentgrid visar alla 25 agenter oavsett vilka som kördes — förvirrande |
| ⚠️ UX | Fel-agenter (status=error) markeras inte tydligt i griden |

---

### [5] Urvalssteg — sendSelectedFynd()
| Status | Observation |
|--------|-------------|
| ✅ Fungerar LOKALT | `POST /api/backlog/add` finns i lokal app.py (rad 3312) |
| ❌ **SAKNAS på origin/main** | Endpoint existerar INTE i origin/main — 404 vid deploy |
| ✅ Dedup | Backend gör dedup-kontroll — dubbletter hoppas över |
| ⚠️ Lock-gap | `_backlog_load()` inne i `backlog_add_items()` körs utan `_backlog_lock` (se P1-L) |
| ⚠️ Limit | Frontend skickar max 40 items men inga valideringen i UI av för lång titel/body |

**KONSEKVENS:** Om branch-divergens löses med Alt A (behåll origin/main) måste denna endpoint porteras manuellt. Om Alt B (behåll lokal) är det driftsklart.

---

### [6] Planeraren — planBacklog()
| Status | Observation |
|--------|-------------|
| ✅ Fungerar LOKALT | `POST /api/backlog/plan` finns i lokal app.py (rad 3337) |
| ❌ **SAKNAS på origin/main** | Endpoint existerar INTE i origin/main — 404 vid deploy |
| ✅ AI-ordning | Kör `run_planner_agent` — returnerar ordning/typ/beroenden |
| ⚠️ Timeout | 120s timeout hårdkodad — fungerar för <20 items men riskabelt vid stort backlog |
| ⚠️ Svar utan ordning | Om planeraren returnerar tom `ordning` → 502-fel, ingen fallback |

---

### [7] Att Bygga-fliken — loadAttBygga()
| Status | Observation |
|--------|-------------|
| ✅ Fungerar | Parallell fetch av backlog + queue |
| ✅ Fungerar | `renderQueueBox()` — fas-lås, grön-gate, expand first actionable |
| 🐛 Bug | `behover_dig`-status **blockerar hela kön** — om ett kort fastnar i behover_dig låser det alla efterföljande jobb (grön-gate) |
| ⚠️ UX | Ingen tydlig indikator för WHY kön är låst — användaren ser bara att inget kan starta |
| 🐛 Bug | Projekt lagras i `localStorage` — försvinner vid datoryte/annan maskin (se P3-R i BUILD_TASKS) |
| ⚠️ Lock | `get_build_queue()` och `advance_build_queue()` anropar `_queue_load()` UTAN `_queue_lock` (se P1-O) |

---

### [8] Bygge — startBuild() — **MANUELLT GAP**
| Status | Observation |
|--------|-------------|
| ✅ Skickar | `POST /api/build-queue/{id}/send` — kopierar spec till clipboard |
| ❌ **MANUELLT GAP** | Spec klistras in manuellt i IDE → kod byggs → klistras tillbaka |
| ❌ **Inget webhook** | Ingen automatisk notifiering när bygget är klart |
| ⚠️ Beroende | Flödet är SYNKRONT på användaren — agenten väntar på manuell action |
| 🔮 Framtid | P2-A/B/C/D i BUILD_TASKS täcker automatisering av detta steg |

**DETTA ÄR DET STÖRSTA OPERATIVA GAPET I SYSTEMET.**  
Allt fram till startBuild() är automatiserat. Allt efter kräver manuell mänsklig handling. Systemet är designat för att *assistera* en byggare, inte ersätta den — men det saknas tydlig dokumentation av detta i UI.

---

### [9] Granska bygge — kontrolleraBuild() / submitBuildResult()
| Status | Observation |
|--------|-------------|
| ✅ Fungerar | `fetchActiveProjectCode()` hämtar kod automatiskt |
| ✅ Fungerar | paste-modal (openBuildResult) som fallback om auto-hämtning misslyckas |
| 🐛 Bug | `openVerifyFix()` pre-fyller från `codeInput` — men `codeInput` är TOM i Att Bygga-vyn (se P3-U i BUILD_TASKS) |
| ⚠️ TOCTOU | `build_queue_review()` sätter `review_started_at` EFTER 3–10 min agentarbete — parallella anrop dubblar agent-körningar (se P1-P) |
| ⚠️ Lock | `build_queue_review()` läser item utan lock i start (se P1-O) |

---

### [10] Godkänn / Gör om
| Status | Observation |
|--------|-------------|
| ✅ Fungerar | Godkänd: status → klar |
| ✅ Fungerar | Underkänd: ny prompt → status → behover_dig |
| ✅ Fungerar | `queueSetStatus()` → PATCH med override_reason för friskförklara |
| ⚠️ UX | "Friskförklara" är en osynlig escape hatch — svår att hitta om man inte vet den finns |
| ⚠️ Gap | Ingen historik över godkännande/underkännande — bara aktuell status sparas |

---

## Kritiska flödesavbrott (måste fixas för driftstabilitet)

### AVBROTT 1 — Branch-divergens bryter urvalssteg + planering vid deploy
**Berörda steg:** [5] och [6]  
**Symptom:** 404 på `/api/backlog/add` och `/api/backlog/plan` om origin/main används  
**Fix:** Se P1-J (branch resolution) + verifiera att endpoints porteras  
**Prioritet:** KRITISK

### AVBROTT 2 — behover_dig låser hela kön utan escape
**Berört steg:** [7]  
**Symptom:** Ett enda misslyckat bygge blockerar alla efterföljande jobb osynligt  
**Fix:** Tydlig visuell indikator + enklare friskförklara-knapp  
**Prioritet:** HÖG

### AVBROTT 3 — TOCTOU i build_queue_review orsakar dubbla agent-körningar
**Berört steg:** [9]  
**Symptom:** Parallella klick på "Kontrollera" startar dubbel AI-granskning (dyr + inkonsistent)  
**Fix:** Sätt `review_started_at` UNDER LOCK vid funktionsingång (se P1-P)  
**Prioritet:** KRITISK

### AVBROTT 4 — openVerifyFix har tom codeInput i Att Bygga-vyn
**Berört steg:** [9]  
**Symptom:** Buggrapporten pre-fylls med tomma fält — användaren måste klistra in kod manuellt  
**Fix:** Hämta kod från aktuellt queue-kort istället för `codeInput` (se BUILD_TASKS P3-U)  
**Prioritet:** MEDEL

---

## Saknade automatiseringssteg (P2-prioritet)

| Gap | Nuläge | Önskat |
|-----|--------|--------|
| Spec → IDE | Manuell clipboard-paste | Webhook/API till byggagent |
| Byggt kod → review | Manuell paste-modal | Auto-hämtning via git-diff eller filsystem |
| Godkänd → deploy | Inget | Auto-push/PR vid godkännande |
| Ny review → notis | Inget | Push-notis/SSE-event till byggaren |

Dessa täcks av **P2-A, P2-B, P2-C, P2-D** i BUILD_TASKS.md.

---

## Projekttillstånd — localStorage-problemet

**Alla projekt-IDs sparas BARA i `localStorage` (index.html).**  
- Försvinner vid byte av webbläsare / inkognito / ny maskin  
- Ingen synkronisering mot backend  
- Om `project_id` tappas bort försvinner all backlog och byggkö för projektet (data finns kvar på servern men är oåtkomlig utan ID)

**Rekommendation:** Projekt bör sparas i Supabase `prompt_sessions`-tabellen med en lista-endpoint. Se BUILD_TASKS P3-R.

---

## Sammanfattning — Flödets mognadsnivå

| Fas | Mognad | Kommentar |
|-----|--------|-----------|
| Granskning (1-4) | 🟢 Hög | Stable, felhantering ok, recovery finns |
| Urval + planering (5-6) | 🟡 Medel | Fungerar lokalt, saknas på origin/main |
| Att Bygga-vy (7) | 🟡 Medel | Lock-gap, localStorage-beroende |
| Bygge (8) | 🔴 Låg | Helt manuellt — det stora gapet |
| Granskning av bygge (9) | 🟡 Medel | TOCTOU, codeInput-bug |
| Godkänn/Om (10) | 🟢 Hög | Fungerar, bara UX-förbättringar kvar |

---

## Rekommenderad åtgärdsordning

1. **P1-J** — Lös branch-divergens (välj Alt A eller Alt B, porta endpoints)
2. **P1-P** — Fixa TOCTOU i build_queue_review (sätt review_started_at under lock)
3. **P1-O** — Lägg till _queue_lock i get_build_queue + advance_build_queue
4. **P1-L** — Lägg till _backlog_lock i alla backlog-läsningar
5. **P3-R** — Flytta projekt-lagring från localStorage till backend
6. **P2-A** — Implementera automatisk spec→byggagent-webhook (bryt det manuella gapet)
7. **P3-T** — Fixa O(n) GC i _progress_set
8. **P2-B/C/D** — Automatisera resterande manuella steg

*Fullständiga task-beskrivningar finns i BUILD_TASKS.md.*
