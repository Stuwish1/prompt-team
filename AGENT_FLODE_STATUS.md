# Flödesagent Status
**Senast analyserad:** 2026-06-10 (automatisk körning)  
*Iteration 10 — baserad på app.py (4683 rader), build_queue.json, PROJECT_STATUS.md*

---

## Flödesöversikt (uppdaterad)

```
[1] LÄGE          Välj ny_funktion / granska_kod / buggrapport
      ↓
[2] GRANSKA       runReview() → POST /api/review  (semaphore: max 3 parallella)
      ↓
[3] PROGRESS      GET /api/progress/{runId}  (1500 ms polling)
      ↓           recoverRunResult() — 12 min fallback om nätdöd
[4] RESULTAT      renderResults() → kravBox, agentGrid, spec
      ↓
[5] URVAL         POST /api/backlog/add
      ↓
[6] PLANERA       POST /api/backlog/plan
      ↓
[7] ATT BYGGA     GET /api/backlog + GET /api/build-queue
      ↓
[8] BYGGE         POST /api/build-queue/{id}/send → auto-dispatch (P2-C klar)
      ↓
[9] GRANSKA BYGGE POST /api/build-queue/{id}/review
      ↓
[10] GODKÄNN/OM   klar | behover_dig → blockerar kön
      ↓
[11] CHATT        POST /api/chat → SSE-streaming (ny kanal, parallell med ovan)
```

---

## Nya fynd sedan sist

### 1. `_chat_sessions` — obegränsad minnestillväxt (MEDIUM)
**Funktion:** `_chat_sessions: dict[str, list] = {}` (rad 104) + `/api/chat`-endpoint  
**Problem:** Chat-sessioner läggs till i `_chat_sessions` men rensas aldrig — ingen GC-loop, ingen TTL, inget max-antal.  
Varje unik `chat_id` skapar en post. Servern läcker minne tills den startas om.  
**Åtgärd:** Lägg till GC-logik i `_progress_gc_loop` eller en separat loop — rensa sessioner äldre än t.ex. 60 min baserat på ett `last_used`-fält.

### 2. `chat_id` är user-supplied utan validering (MEDIUM)
**Funktion:** `chat(payload)` → `chat_id = payload.get("chat_id", "default")` (rad ~2350)  
**Problem:** Vilken sträng som helst accepteras som session-nyckel. En angripare kan skicka tusentals anrop med unika chat_id-värden och tömma serverns minne systematiskt.  
**Åtgärd:** Begränsa `chat_id` till max 64 tecken alfanumeriskt, och/eller koppla det till ett projektkontext.

### 3. Chat-historik sparar inte tool-call-innehåll (LOW)
**Funktion:** `stream()`-generatorn i `/api/chat`  
**Problem:** Efter ett `tool_use`-varv sparas bara textblock tillbaka till `_chat_sessions`:
```python
text_content = " ".join(b.text for b in assistant_content if hasattr(b, 'text'))
_chat_sessions[chat_id].append({"role": "assistant", "content": text_content})
```
Tool-calls och tool-results sparas inte i historiken. Om sessionen fortsätter i ett nytt anrop saknas kontexten från verktygsanvändning — agenten "glömmer" vad den gjort.  
**Åtgärd:** Spara hela `final_message.content` (lista med block) som `content` för assistant-meddelandet, inte bara hopfogad text.

### 4. Aktivt `behover_dig`-item blockerar `instr-test`-projektet (INFO)
**Data:** `build_queue.json` — item `afab95c3` (project_id: `instr-test`, title: "Instruktionstest") har `status: "behover_dig"` utan `deleted_at`.  
**Konsekvens:** Hela `instr-test`-projektets kö är låst via grön-gate. Ser ut som testdata som aldrig städats bort.  
**Åtgärd:** Antingen soft-delete itemet eller friskförklara det med motivering.

### 5. app.py avslutas korrekt — BUG-KRITISK radtruncering är LÖST
Filen slutar korrekt på rad 4683 med `get_project_settings_api`. Den tidigare rapporterade trunkationen vid rad 4676 är åtgärdad.

---

## Rekommendationer (prioriterade)

1. **[MEDIUM] Lägg till GC för `_chat_sessions`** — rensning var 5–10 min, TTL 60 min per session. Gör det i `_progress_gc_loop` som redan körs eller i en ny loop. Utan detta läcker minnet vid drift.

2. **[MEDIUM] Validera `chat_id`** — begränsa till max 64 alfanumeriska tecken. Returnera HTTP 400 om ogiltigt format. Stoppar minnesangrepp via unika session-nycklar.

3. **[LOW] Fixa historik-sparning i chat** — spara `final_message.content` (komplett lista) i stället för sammanfogad text. Säkrar konversationskontinuitet efter tool-use.

4. **[INFO] Städa testdata i `build_queue.json`** — soft-delete `afab95c3` (instr-test) manuellt.

---

## Tidigare flaggat (fortfarande relevant)

### Manuellt gap i byggflödet (steg 8)
- Auto-dispatch (P2-C) är implementerat men flödet är fortfarande semi-manuellt — ingen polling/notifiering när byggaren är klar.
- Täcks av framtida SSE endpoint `/api/builder/stream/{id}` (per AGENT_CHATBOX_BUILD.md).

### Projekttillstånd i localStorage
- `project_id` lagras bara i webbläsarens localStorage. Försvinner vid byte av maskin/incognito.
- P3-R är markerat som löst (kontrolleraBuild() återinförd) men backend-projektsync saknas fortfarande.

### UX — friskförklara är dold escape hatch
- Ingen tydlig visuell indikator för varför kön är låst, eller var friskförklara-knappen finns.
- Fortfarande öppet UX-förbättringsarbete (AGENT_UX_STATUS.md).

---

## Löst sedan sist (iteration 9 → 10)

| Åtgärd | Verifierat |
|--------|-----------|
| P3-T: `_progress_set()` GC → bakgrundsjobb (`_progress_gc_loop`, rad 3137) | ✅ Koden bekräftad |
| P1-O: `get_build_queue()` och `advance_build_queue()` läser nu under `_queue_lock` | ✅ Koden bekräftad |
| P1-P: TOCTOU i `build_queue_review()` åtgärdad | ✅ Per PROJECT_STATUS |
| P1-L: backlog-läsning under `_backlog_lock` | ✅ Per PROJECT_STATUS |
| CHAT-1/CHAT-2: Backend + frontend chattflik med SSE-streaming | ✅ Implementerat |
| P2-A/B/C/D: Auto-dispatch, GitHub push, chatt-panel | ✅ Per PROJECT_STATUS |
| BUG-KRITISK: app.py trunkerad vid rad 4676 | ✅ Filen komplett (4683 rader) |

---

## Sammanfattning — Flödets mognadsnivå

| Fas | Mognad | Kommentar |
|-----|--------|-----------|
| Granskning (1–4) | 🟢 Hög | Semaphore, recovery, GC — stabilt |
| Urval + planering (5–6) | 🟡 Medel | Fungerar lokalt; branch-divergens (P1-J) kräver Stivens beslut |
| Att Bygga-vy (7) | 🟡 Medel | localStorage-beroende kvarstår |
| Bygge (8) | 🟡 Medel | Auto-dispatch implementerat, notifiering saknas |
| Granskning av bygge (9) | 🟢 Hög | TOCTOU löst, auto-hämtning fungerar |
| Godkänn/Om (10) | 🟢 Hög | Stabilt |
| Chatt (11) | 🟡 Medel | Fungerar — minnesleak och historik-bug kvarstår |

*Fullständiga task-beskrivningar finns i BUILD_TASKS.md.*
