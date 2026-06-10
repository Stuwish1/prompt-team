# Arkitekturanalys — Prompt Team
*Datum: 2026-06-10 | Senast uppdaterad: iteration 5 | Baserad på origin/main: `3654bd7`*

---

## 1. Det befintliga systemet — hur det fungerar idag

### Tre lägen, ett syfte
Systemet har en FastAPI-backend (`app.py`, 4 025 rader) och en vanilla-JS-frontend (`index.html`, ~197 k). Det finns tre vyer:

| Vy | Syfte |
|---|---|
| **Beställ** | Idé/kod/bugg in → AI-team granskar → spec ut |
| **Att bygga** | Backlog + byggkö — specs väntar på att byggas |
| **Historik** | Alla tidigare körningar |

---

## 2. Fullständigt flöde — steg för steg

```
[ANVÄNDAREN]
     │
     ▼
┌──────────────────────────────────────────────┐
│  VY: BESTÄLL                                  │
│                                               │
│  Tre ingångar:                                │
│    • Ny funktion  (idé)                       │
│    • Granska kod  (befintlig kod)             │
│    • Buggrapport  (symptom + kod)             │
└──────────────────────┬───────────────────────┘
                       │ POST /api/review
                       ▼
┌──────────────────────────────────────────────┐
│  STEG 1: Kravanalytikern (gate)              │
│                                               │
│  • Om FÖR_VAGT → returnerar frågor till UI   │
│  • Om TILLRÄCKLIGT → fortsätter               │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  STEG 2: 29 specialistagenter (parallellt)   │
│                                               │
│  Pre-lager:  Hotmodelleraren, Dataskyddsjur.  │
│  Arkitektur: Arkitekten, Integratören, Risk   │
│  Design/FE:  UX, UI, Frontend, Responsiv,    │
│              Tillgänglighet                   │
│  Backend:    Databas, Datamigration, API,     │
│              Felhantering, Edge-case           │
│  Kvalitet:   Kodkvalitet, Säkerhet,           │
│              Hemlighets vakten, Prestanda,    │
│              Skalbarhet, Dataintegritet       │
│  Testning:   Testaren                         │
│  Visuell QA: Visual QA (multimodal)           │
│  Bug-mode:   Rotorsaksanalytikern             │
└──────────────────────┬───────────────────────┘
                       │ (parallellt med steg 3)
                       ▼
┌──────────────────────────────────────────────┐
│  STEG 3+4: Backloghållaren + Promptsmeden    │
│           (körs parallellt med varandra)      │
│                                               │
│  • Backloghållaren → strukturerar fynd        │
│    som P0/P1/P2 backlog-items                 │
│  • Promptsmeden (Claude Sonnet) → syntetiserar│
│    all feedback till en handlingsbar spec     │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  STEG 5+6: Kompletthetsgranskaren +          │
│            Beställarsammanfattaren            │
│           (parallellt, konsumerar specen)     │
│                                               │
│  • Kompletthetsgranskaren → score 1-10,      │
│    saknade delar flaggas                      │
│  • Beställarsammanfattaren → klarspråk för   │
│    icke-kodare                                │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  RESULTAT visas i UI:                         │
│    • Beställarläge (enkel vy)                │
│    • Teknisk läge (full spec)                │
│    • Fynd att välja bland                     │
│                                               │
│  Användaren bockar i fynd →                  │
│  "→ Skicka valda till Att bygga"             │
└──────────────────────┬───────────────────────┘
                       │ POST /api/backlog/add
                       ▼
┌──────────────────────────────────────────────┐
│  VY: ATT BYGGA — Backlog                     │
│                                               │
│  Fynd (P0/P1/P2) synliga här                 │
│  "📐 Planera ordning" → Planeraren (AI)       │
│    sätter byggordning efter beroenden         │
│                                               │
│  Varje backlog-item kan konverteras till spec │
│  (POST /api/backlog/{id}/to-spec)            │
│    → Fas-uppdelning för L-ärenden            │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  VY: ATT BYGGA — Byggkö                      │
│  Status: kö → byggs → klar | behover_dig     │
│                                               │
│  WIP-limit: max 1 aktivt bygge per projekt   │
│  Grön-gate: underkänt bygge blockerar kön    │
│  Fas-lås: fas N kräver fas N-1 klar          │
└──────────────────────┬───────────────────────┘
                       │ POST /api/build-queue/{id}/send
                       ▼
┌──────────────────────────────────────────────┐
│  JOB-KONTRAKT skapas (returneras till UI)    │
│                                               │
│  job = {                                      │
│    spec_markdown,                             │
│    builder_instruktion,                       │
│    callback: {                                │
│      result: /api/build-queue/{id}/result    │
│      review: /api/build-queue/{id}/review    │
│    }                                          │
│  }                                            │
│                                               │
│  ⚠️  DAGENS MANUELLA STEG:                   │
│  Användaren kopierar spec →                  │
│  klistrar in i Lovable/Cursor/Claude Code    │
└──────────────────────┬───────────────────────┘
                       │ (manuellt idag)
                       ▼
┌──────────────────────────────────────────────┐
│  BYGGAREN levererar (manuellt idag)          │
│                                               │
│  Alternativ A: Klistra in kod i UI           │
│    → POST /api/build-queue/{id}/result       │
│                                               │
│  Alternativ B: Hämta från GitHub             │
│    → "🔍 Kontrollera"-knapp                  │
│    → POST /api/github/fetch                  │
│    → POST /api/build-queue/{id}/review       │
└──────────────────────┬───────────────────────┘
                       │ POST /api/build-queue/{id}/review
                       ▼
┌──────────────────────────────────────────────┐
│  AUTOMATISK GRANSKNING (redan implementerad) │
│                                               │
│  1. Fullt granska_kod-review av byggd kod    │
│  2. Verifiering mot ursprungligt backlog-fynd│
│  3. Räknar nya P0:or                         │
│                                               │
│  Verdict:                                     │
│    ✅ klar = inga nya P0 + källfynd fixat    │
│    ❌ behover_dig = nya P0 ELLER ej fixat    │
│                                               │
│  Vid underkänt: spec skrivs om med           │
│  kvarståendena inarbetade →                  │
│  ny omgång med uppdaterad spec               │
└──────────────────────────────────────────────┘
```

---

## 3. Vad som fungerar bra

- **Grön-gate-systemet** är robust: underkänt bygge blockerar hela kön — man kan inte bygga vidare på trasig grund.
- **Fas-låset** är korrekt: komplexa ärenden delas i ordnade faser, fas N kräver fas N-1 klar.
- **Spec-omskrivning vid underkänt** är smart: byggaren får inte samma spec igen + en bilaga, utan en omskriven spec där kvarståendena är inbakade som krav.
- **Retry-logiken** och kostnadsuppföljningen per agent är välgjord.
- **Job-kontraktet** från `/send` är redan strukturerat för att en extern byggare ska kunna anropa callback — koden är redo, men loopen är inte sluten.

---

## 4. GAP — det som saknas

### GAP 1: Den manuella bryggan (KRITISK)
Koden innehåller kommentaren *"Today: human copies job.spec_markdown. Tomorrow: an adapter POSTs job to a builder."* — detta är det enda steg i hela flödet som fortfarande är manuellt. Användaren måste:
1. Kopiera spec manuellt
2. Öppna externt verktyg (Cursor, Lovable, etc.)
3. Klistra in och vänta
4. Kopiera tillbaka resultatet

Det är ett UX-avbrott mitt i ett annars sammanhållet flöde.

### GAP 2: Ingen inbyggd chatt-ruta
Det finns ingen konversationsyta i appen. Tanken är att det ska finnas en chatt-ruta (likt den du och jag sitter i nu) som:
- Tar emot job-kontraktet automatiskt från Bygg-fliken
- Låter en Claude-agent bygga koden inuti appen
- Auto-pushar till GitHub
- Rapporterar tillbaka via callback-URL:erna

### GAP 3: Ingen auto-push efter bygge
GitHub-integrationen kan *hämta* kod (fetch), men kan inte *pusha* kod. Byggaren måste fortfarande pusha manuellt.

### GAP 4: Ingen automatisk callback
Efter att byggaren är klar finns det ingen mekanism som automatiskt triggar `/api/build-queue/{id}/review`. Det kräver ett manuellt klick.

### GAP 5: Ingen koppling idé → befintligt system
Det saknas ett steg som kan kontrollera om en ny idé krockar med eller duplicerar något som redan finns i systemet. Idag körs granskning mot en ögonblicksbild av koden — det finns ingen "baseline-validering" som säger "det här finns redan, bygg inte det igen."

---

## 5. Föreslagen arkitektur — det kompletta flödet

```
[NY IDÉ / KOD / BUGG]
        │
        ▼
   Beställ-vy
   (befintlig, fungerar)
        │
        ▼
   29 agenter + Promptsmeden
   → Spec skapas
        │
        ▼
   Fynd väljs → Backlog
        │
        ▼
   Planeraren → Byggordning
        │
        ▼
   Byggkö: "▶ Bygg nästa"
        │
        ├──── IDAG: manuell kopia ──────────────────────────────────┐
        │                                                            │
        │ IMORGON (det vi ska bygga):                               │
        ▼                                                            │
┌────────────────────────────────┐                                  │
│  CHATT-RUTAN (ny komponent)    │                                  │
│                                │                                  │
│  Job-kontraktet postas in      │                                  │
│  automatiskt när "Bygg nästa" │                                  │
│  trycks                        │                                  │
│                                │                                  │
│  Claude Code Agent:            │                                  │
│  • Läser spec                  │                                  │
│  • Bygger koden                │                                  │
│  • Pushar till GitHub          │◄──────────────────────────────────┘
│  • Rapporterar tillbaka via    │
│    /result + /review callback  │
└────────────────┬───────────────┘
                 │ Auto-callback
                 ▼
   /api/build-queue/{id}/review
   (befintlig, fungerar redan)
                 │
                 ▼
        ✅ klar  eller  ❌ behover_dig
                 │
                 ▼ (om behover_dig)
   Spec skrivs om med kvarståendena
                 │
                 ▼
   Nytt prompt postas in i chatt-rutan
   → ny byggrunda startar automatiskt
```

---

## 6. Byggplan för chatt-rutan

### Vad chatt-rutan behöver göra

1. **Ta emot job** — när användaren trycker "▶ Bygg nästa" skickas `job`-objektet till chattrutan istället för (eller parallellt med) att visas som kopierbar text.
2. **Visa konversation** — meddelandevy likt Claude.ai: spec visas som ett systemmeddelande, agentens svar strömmas in.
3. **Trigga bygget** — backend skapar en Claude Code-session med spec som systemkontext + instruktion att bygga och pusha.
4. **Auto-push** — agenten kör `git commit && git push` mot repo/branch i projektprofilen.
5. **Auto-callback** — när agenten svarar klart, anropa `job.callback.result` + `job.callback.review` automatiskt.
6. **Visa verdict** — resultatet från granskningen visas direkt i chattrutan: ✅ grön eller ❌ röd med kvarståendena listade.
7. **Loop vid underkänt** — om `behover_dig`, postas omskriven spec automatiskt in som nästa meddelande i chattrutan.

### Backend-endpoints att lägga till

```
POST /api/chat/session          → Starta en ny chatt-session kopplad till queue-item
POST /api/chat/{session}/message → Skicka meddelande (human eller system)
GET  /api/chat/{session}/stream  → SSE-ström av agentens svar
POST /api/chat/{session}/close   → Stäng session (rensar upp resurser)
```

### Steg att implementera (i ordning)

| # | Steg | Notering |
|---|------|----------|
| 1 | Chatt-UI i "Att bygga"-vyn | Slide-in panel eller modal under byggkö-item |
| 2 | `/api/chat/session` + SSE-ström | Ström agentens tokens direkt till UI |
| 3 | Auto-inject job i chattrutan | `startBuild()` postar job till chattsessionen |
| 4 | Agenten bygger + pushar | Claude Code med git-verktyg aktiverade |
| 5 | Auto-callback till `/result` + `/review` | Körs i callback när agenten svarar klart |
| 6 | Visa verdict inline i chatten | Grön/röd banner + kvarståendelista |
| 7 | Auto-reloop vid underkänt | Omskriven spec postas automatiskt som nästa meddelande |

---

## 7. Kontroll mot befintligt system (baseline-validering)

För att undvika att bygga något som redan finns:

```
Ny idé → Kravanalytikern → innan specialistagenter:
  Ny agent: "Baslinjegranskaren"
    • Hämtar /api/github/fetch på nuvarande HEAD
    • Kontrollerar om idéns krav redan är implementerade
    • Svar: FINNS_REDAN | DELVIS | SAKNAS
    • Vid FINNS_REDAN: returnerar var i koden det finns → användaren bestämmer
```

---

## 8. Sammanfattning — vad som är klart vs. saknas

| Komponent | Status |
|-----------|--------|
| 29 specialistagenter + granskning | ✅ Klart |
| Kravanalytiker + vag-input-gate | ✅ Klart |
| Backlog med P0/P1/P2 + dedup | ✅ Klart |
| Planeraren + fas-uppdelning | ✅ Klart |
| Byggkö med WIP-limit + grön-gate | ✅ Klart |
| Job-kontrakt med callback-URL:er | ✅ Klart (men ej inkopplat) |
| Spec-omskrivning vid underkänt | ✅ Klart |
| Auto-granskning efter bygge | ✅ Klart |
| GitHub fetch (hämta kod) | ✅ Klart |
| **Inbyggd chatt-ruta** | ❌ Saknas |
| **Auto-dispatch till agent** | ❌ Saknas |
| **GitHub push (pusha kod)** | ❌ Saknas |
| **Auto-callback efter bygge** | ❌ Saknas |
| **Auto-reloop vid underkänt** | ❌ Saknas |
| **Baslinjevalidering mot befintlig kod** | ❌ Saknas |

---

## 9. Nya fynd — tekniska och UX-problem (iteration 2)

### 9a. sessions.json — tidsbomb (KRITISK)
Filen är redan 4 MB och läses in i sin helhet i minnet varje gång en session sparas eller listas. Det finns ingen paginering, ingen arkivering och ingen storleksgräns. Vid normal drift med dagliga körningar kan filen växa till hundratals MB inom månader, vilket ger märkbara latenser och minnestoppar.

**Åtgärd:** Inför paginering i `/api/sessions` (offset+limit), arkivera sessioner äldre än X dagar till en separat `sessions_archive.json`, och lägg aldrig hela filen i minnet — läs rad för rad eller migrera till SQLite.

---

### 9b. Ingen autentisering (KRITISK)
Appen lyssnar på port 8001 utan lösenord eller token-skydd. CORS är låst till localhost — det skyddar mot cross-site-anrop men inte mot en angripare på samma nätverk eller maskin. `settings.json` innehåller API-nycklar, GitHub-token och Supabase-nyckel i klartext.

**Åtgärd:** Minst ett enkelt statiskt lösenord (Basic Auth eller en hemlig Bearer-token i `settings.json`) som skyddar alla `/api/*`-endpoints. Lösenordet sätts vid installation.

---

### 9c. Projektdata lever bara i localStorage
Projektnamn, repo-URL, branch, constraints och byggsätt lagras i webbläsarens localStorage. Det innebär att:
- Öppnar man appen i en annan webbläsare eller på en annan dator är all projektsetup försvunnen.
- Det finns ingen backup.
- Det går inte att dela ett projekt med en kollega.

**Åtgärd:** Flytta projektprofiler till servern (fil eller Supabase). Läs/spara via `/api/projects`.

---

### 9d. GitHub-integrationen är read-only
`/api/github/fetch` kan hämta kod men det finns ingen endpoint för att pusha. Alla kommentarer om "byggaren ska pusha till GitHub" förutsätter att byggaren gör det manuellt. Systemet kan aldrig själv committa eller pusha.

**Åtgärd:** Lägg till `/api/github/push` som använder GitHub Contents API (`PUT /repos/{owner}/{repo}/contents/{path}`) för att committa enstaka filer, eller kör `git push` via subprocess om repot är klonat lokalt. Detta är en förutsättning för att chatt-agenten ska kunna sluta loopen automatiskt.

---

### 9e. _RUN_RESULTS försvinner vid serveromstart
Körningsresultat cachas i `_RUN_RESULTS` — en in-memory dict som töms när processen startar om. Recovery-mekanismen (`/api/review/result/{run_id}`) fungerar bara om exakt samma process lever. En serveromstart mitt i en körning (t.ex. vid deployment) gör att frontend aldrig får tillbaka resultatet.

**Åtgärd:** Skriv ut varje körningsresultat till en liten temp-fil på disk (`build_results/run_{run_id}.json`) vid stash, och läs därifrån i recovery-endpointen. Rensa filer äldre än 2 timmar vid startup.

---

### 9f. Visual QA-agenten aktiveras aldrig automatiskt
Agenten `visual_qa` kräver att användaren manuellt bifogar en skärmdump. Vid `kontrolleraBuild` (GitHub-hämtning) skickas inga skärmdumpar — agenten hoppar över och returnerar GODKÄND. Det innebär att visuell kvalitetssäkring aldrig sker automatiskt i den automatiserade loopen.

**Åtgärd i chatt-loopen:** När agenten bygger och pushar, ta en headless-screenshot (t.ex. via Playwright) av applikationen och bifoga den automatiskt till `/review`-anropet.

---

### 9g. Hemlighetsvakten blockerar inte — den flaggar bara
Hemlighetsvakten hittar API-nycklar och credentials i koden, men fyndet hamnar i backloggen som en P0 precis som alla andra. Inget stoppar att koden ändå pushas och körs. I en automatiserad loop är detta extra känsligt — chatt-agenten kan pusha kod med hårdkodade nycklar om den inte stoppas.

**Åtgärd:** Lägg till ett hårt block i `/api/build-queue/{id}/review`: om `hemlighetsvakten` returnerar UNDERKÄND → sätt automatiskt status `behover_dig` oavsett övrig granskning och lägg till en varning i verdiktet. Hemligheter är icke-förhandlingsbara.

---

### 9h. Snabbläget garanterar inte säkerhetsagenter
`_QUICK_AGENT_IDS` inkluderar `security` men inte `hemlighetsvakten` eller `dataskyddsjuristen`. En snabb iteration kan alltså missa GDPR-problem och exponerade nycklar.

**Åtgärd:** Lägg till `hemlighetsvakten` och `dataskyddsjuristen` i `_QUICK_AGENT_IDS` — de är snabba agenter med lite output och ska alltid köra oavsett djup.

---

### 9i. Sessionsnamn baseras på råtext, inte tolkad idé
`auto_name()` tar de första 7 orden av inputtexten som namn. Det ger namn som `"itterera · 10 Jun"`. Kravanalytikerns `tolkad_ide`-fält innehåller en meningsfull sammanfattning men används aldrig som sessionsnamn.

**Åtgärd:** Om `krav_result.get("tolkad_ide")` finns och är kortare än 60 tecken — använd det som sessionsnamn. Fallback på nuvarande logik.

---

### 9j. Spec-versioner sparas men syns aldrig i UI
Vid omskrivning efter underkänt bygge sparas gamla versioner i `spec_versions[-5:]`. Det finns dock inget UI för att se skillnaden mellan version 1 och version 2. Användaren kan inte förstå vad som ändrades.

**Åtgärd:** Lägg till en "📜 Versionshistorik"-knapp på byggkö-kortet. Visar en lista med `försök → spec_markdown` för de senaste 5 versionerna. Diff kan visas med en enkel `diff`-funktion i JavaScript.

---

### 9k. Fas-uppdelning saknar gruppvy
När ett L-ärende delas i t.ex. 3 faser skapas 3 separata kö-items. Det finns ett `fas_grupp`-fält och fas-lås, men det finns ingen vy som visar alla 3 faser som en sammanhållen enhet med övergripande progress (fas 1 klar ✅, fas 2 byggs ⏳, fas 3 väntar 🔒).

**Åtgärd:** Gruppera fas-items visuellt i byggkön under en kollapsbar "fas-grupp"-rad med samlad progress-indikator.

---

### 9l. Ingen kostnadsdashboard
Kostnad per körning sparas och redovisas i resultatsidan, men aggregeras aldrig. Det finns ingen vy för "total kostnad denna vecka" eller "dyraste agenten senaste månaden". För ett stort IT-bolag med många dagliga körningar är detta en blind fläck.

**Åtgärd:** Lägg till ett kostnadsaggregat i `/api/sessions` (sum av `stats.cost_total` per tidsperiod) och visa det som ett enkelt sparkline-diagram i historikfliken.

---

### ~~9m. Buggläge kräver manuell kodinmatning~~ ✅ FELAKTIGT FYND — STÄNGT
Efter kodgranskning: `usesCode = mode === 'granska_kod' || mode === 'buggrapport'` — buggrapport auto-hämtar redan kod från GitHub om ett projekt är kopplat. Inget att åtgärda.

---

### 9n. Stale "byggs"-status blockerar hela kön vid omstart (KRITISK)
`startup()` kör bara `_migrate_sessions()` — det återställer **inte** items som fastnat i "byggs"-status. Om servern startar om medan ett bygge pågår (deployment, krasch, strömavbrott) stannar itemet i "byggs" för evigt. WIP-limiten tillåter bara ett aktivt bygge per projekt, vilket innebär att hela byggkön är permanent blockerad. Användaren ser bara ett låst kort utan förklaring.

**Åtgärd:** Lägg till i `startup()`: återställ alla items med `status == "byggs"` till `status == "kö"` och logga `"reset_after_restart"`. Visa även en tydlig varning i UI om något item sitter i "byggs" utan `sent_at` under senaste 30 minuterna.

---

### 9o. Ingen gräns för simultana granskningar
`/api/review` har ingen rate-limiting eller semaphore. Flera användare (eller dubbla-klick) kan starta 4–5 granskningar parallellt. Varje granskning spawnar ~20 agenter = ~100 trådar mot en pool av 80 → agent-timeouts som ser ut som fel. Inget stoppar detta.

**Åtgärd:** En asyncio-semaphore på t.ex. 3 simultana granskningar (`asyncio.Semaphore(3)`) räcker. Returnera `HTTP 429` med "Tre granskningar körs redan — försök om en stund" om taket nås.

---

### 9p. build_queue.json och backlog.json växer med tombstones
Raderade items soft-deleteas (`deleted_at` sätts) men städas aldrig bort fysiskt. Filen läses in i sin helhet vid varje queue-operation (under lock). Samma tillväxtproblem som sessions.json, fast långsammare.

**Åtgärd:** I `startup()` — komprimera `build_queue.json` och `backlog.json` genom att ta bort items där `deleted_at` är äldre än 30 dagar. Behåll inga tombstones längre än nödvändigt.

---

### 9q. ai_eval.py och test-filer är inte versionsskyddade
`ai_eval.py`, `test_intrim.py` och `intrim_result.json` är bra testverktyg men de körs manuellt och är inte kopplade till någon CI-gate. `intrim_result.json` innehåller råa API-svar från testkörningar och borde inte ligga committat. Det finns ingen automatisk spärr som hindrar att en buggig `app.py` pushas utan att testerna körs.

**Åtgärd:** Lägg till `intrim_result.json` och `ai_eval_results.json` i `.gitignore`. Skriv ett GitHub Actions-workflow (`.github/workflows/e2e.yml`) som kör `e2e_test.py` mot en lokal serverinstans på varje push till `main`.

---

### 9n. Ingen inbound webhook från GitHub
Systemet kan inte ta emot händelser från GitHub. Det måste alltid triggas manuellt. I en automatiserad pipeline hade en webhook på `push`-händelser kunnat trigga en automatisk kod-granskning direkt.

**Åtgärd (framtida):** Lägg till `POST /api/webhook/github` som verifierar signaturen (`X-Hub-Signature-256`) och triggar en granska_kod-körning vid push mot konfigurerad branch.

---

## 10. Nya fynd — iteration 4

### 9r. `start.bat` → `uvicorn reload=True` kör i produktionsläge (KRITISK)
`app.py`'s `__main__`-block startar servern med `uvicorn.run(..., reload=True)`. Reload-läget vaktar på alla `.py`-filer och startar om servern automatiskt vid ändringar — inklusive om en agent av misstag skriver till en Python-fil under en pågående granskning. Varje omstart tappar `_RUN_RESULTS` och `_progress` in-memory, vilket innebär att alla aktiva körningar dör tyst.

**Åtgärd:** Ändra till `reload=False` i `__main__`. Använd 
---

## 14. Nya fynd — iteration 8

### 14a. `get_backlog()` läser utan lås — race condition mot parallella granskningar (KRITISK)
`GET /api/backlog` anropar `_backlog_load()` utan `_backlog_lock`. Alla skrivoperationer (`backlog_add_items`, `update_backlog_item`, `promote_backlog_item`) hålls under `_backlog_lock`. En granskningskörning som skriver nya backlog-items via `run_backlog_agent` kan överlappa med en läsning → delvis skriven JSON läses in → API returnerar korrupt eller ofullständig data. Vid hög last (flera parallella granskningar) inträffar detta rutinmässigt.

**Åtgärd:** Lägg till `with _backlog_lock:` runt `_backlog_load()`-anropet i `get_backlog()`:
```python
async def get_backlog(project_id: str = ""):
    with _backlog_lock:
        items = _backlog_load()
    ...
```

---

### 14b. `PATCH /api/build-queue/{id}` saknar storleksvalidering på `spec_markdown` — DoS-risk
`patch_build_queue()` gör `item["spec_markdown"] = payload["spec_markdown"]` utan längdbegränsning. En angripare (eller buggy klient) kan skicka en spec_markdown på t.ex. 50 MB. Hela `build_queue.json` skrivs om — filen exploderar i storlek. Nästa läsning under `_queue_lock` slöar ner hela servern. Varje byggreview-anrop laddar filen i sin helhet.

**Åtgärd:** Begränsa till max 100 000 tecken:
```python
if "spec_markdown" in payload:
    val = str(payload["spec_markdown"])
    if len(val) > 100_000:
        return JSONResponse({"error": "spec_markdown överstiger 100 000 tecken."}, status_code=400)
    item["spec_markdown"] = val
```

---

### 14c. `queue_create_item()` accepterar `project_id=""` — items blöder in i alla projektvyer
Items skapas med `project_id` direkt från payload utan validering. En tom sträng passerar igenom. `get_build_queue(project_id="")` returnerar alla items oavsett projekt — items utan korrekt `project_id` visas i alla projektvyer.

**Åtgärd:** I `POST /api/build-queue` — kräv icke-tom `project_id`:
```python
project_id = (payload.get("project_id") or "").strip()
if not project_id:
    return JSONResponse({"error": "project_id krävs."}, status_code=400)
```

---

### 14d. `_sig_tokens()` dedup är ytlig — 6-teckensprefixar missar parafraseringar
Backlog-dedup bygger på 6-teckensprefixar av ord i titel + finding. Två issues med identisk innebörd men olika ordval (`"saknas validering"` vs `"ingen kontroll"`) skapar dubbletter. Omvänt kan orelaterade issues dela prefixord och falskt flaggas som samma. `_is_same_issue()` med 0.5-tröskel är för aggressiv vid korta token-set.

**Åtgärd (kortsiktig):** Höj tröskeln och kräv minimiöverlapp:
```python
def _is_same_issue(a_tokens: set, b_tokens: set) -> bool:
    if not a_tokens or not b_tokens or len(a_tokens) < 2 or len(b_tokens) < 2:
        return False
    inter = len(a_tokens & b_tokens)
    return inter >= 3 and inter / min(len(a_tokens), len(b_tokens)) >= 0.65
```
**Åtgärd (långsiktig):** Ersätt prefix-dedup med cosine-likhet via `/embeddings`-endpoint (> 0.85).

---

*Dokumentet uppdateras automatiskt vid varje iteration. Skicka enskilda P1/P2/P3-block till din byggare som fristående specifikationer.*

---

## 15. Nya fynd — iteration 9

### 15a. `GET /api/build-queue` och `advance_build_queue()` läser utan lås
`get_build_queue()` (rad ~437) och `advance_build_queue()` (rad ~591) anropar `_queue_load()` utan `_queue_lock`. Mönstret är identiskt med den redan funna `get_backlog()`-rasen (14a). Under en `/send`- eller `/patch`-operation kan en parallell GET läsa delvis skriven data. `advance_build_queue` används av "Bygg nästa"-knappen — om den läser stale data kan den returnera ett item som precis fått status `byggs` i ett annat anrop och WIP-kontrollen kringgås i UI (backend-sendet skyddar fortfarande under lock).

**Åtgärd:** Samma fix som 14a — wrappa med `with _queue_lock:`:
```python
async def get_build_queue(project_id: str = ""):
    with _queue_lock:
        items = _queue_load()
    ...

async def advance_build_queue(project_id: str = ""):
    with _queue_lock:
        items = _queue_load()
    ...
```

---

### 15b. `build_queue_review()` har TOCTOU — initial läsning utan lås, `review_started_at` sätts för sent
`build_queue_review()` läser `item` vid funktionsstarten utan `_queue_lock` (rad ~2871). Sedan kör 25 agenter i 3–10 minuter. Först därefter sätts `review_started_at` under lock. Det innebär att P1-K-skyddet (kontroll av `review_started_at`) aldrig kan fånga ett andra anrop som kom in medan agenterna körde — det andra anropet läser också `review_started_at=None` (ännu ej satt) och startar en andra fullgranskning parallellt. Resultaten skriver över varandra i `last_verdict`.

**Åtgärd:** Sätt `review_started_at` OMEDELBART under lock i början av funktionen, innan agenterna startar:
```python
# Läs och lås direkt — sätt review_started_at innan agenter startar
with _queue_lock:
    items = _queue_load()
    item = next((i for i in items if i.get("id") == item_id and not i.get("deleted_at")), None)
    if not item:
        return JSONResponse({"error": "Item hittades inte."}, status_code=404)
    if item.get("review_started_at"):
        return JSONResponse({"error": "En granskning pågår redan."}, status_code=409)
    item["review_started_at"] = datetime.now().isoformat(timespec="seconds")
    _queue_write(items)
# Nu kan agenter köra — review_started_at är satt och blockerar parallella anrop
```

---

### 15c. `backlog_to_spec()` och `backlog_verify_fix()` läser utan lås
`POST /api/backlog/{id}/to-spec` (rad 2675) och `POST /api/backlog/{id}/verify` (rad ~2791) anropar `_backlog_load()` utan `_backlog_lock` för det initiala item-uppslaget. Om en granskningskörning lägger till items i backloggen precis när `to-spec` läser kan stale data returneras — item kan saknas trots att det finns, eller ha ett utdatat `finding`/`suggestion`-fält när det används som seed för Promptsmeden.

**Åtgärd:** Wrappa initiala läsningar med lock (samma fix som 14a):
```python
# I backlog_to_spec:
with _backlog_lock:
    items = _backlog_load()
item = next((i for i in items if i.get("id") == item_id), None)

# I backlog_verify_fix:
with _backlog_lock:
    items = _backlog_load()
item = next((i for i in items if i.get("id") == item_id), None)
```

---

### 15d. `_progress_set()` kör GC på varje anrop — O(n) vid hög last
`_progress_set()` kör en O(n) GC-loop (tar bort entries äldre än 15 min) på varje anrop. Med 25 agenter per granskning och 3 simultana granskningar = 75 GC-loopar under `_progress_lock` per körning. Alla dessa håller `_progress_lock` i turen sin, vilket blockerar `GET /api/progress/{id}` (SSE-polling från frontend). Vid hög last kan progress-uppdateringar fördröjas vilket gör att UI:t verkar hängt.

**Åtgärd:** Flytta GC till ett separat bakgrundsjobb som körs var 5:e minut:
```python
async def _progress_gc_loop():
    while True:
        await asyncio.sleep(300)
        cutoff = datetime.now().timestamp() - 900
        with _progress_lock:
            stale = [k for k, v in _progress.items() if v.get("updated", 0) < cutoff]
            for k in stale:
                _progress.pop(k, None)

@app.on_event("startup")
async def startup():
    ...
    asyncio.ensure_future(_progress_gc_loop())
```

---

*Dokumentet uppdateras automatiskt vid varje iteration. Skicka enskilda P1/P2/P3-block till din byggare som fristående specifikationer.*
im_result*.json`) ur `.gitignore`. Nu är hela `intrim_result*`-mönstret utan skydd. Nästa `git add .` riskerar att committa råa API-testsvar med fullt payload-innehåll.

**Åtgärd:** Lägg tillbaka `intrim_result*.json` i `.gitignore` omedelbart.

---

### 10b. Lokal branch divergerar från origin/main (8 commits)
Den lokala koden är 8 commits FÖRE origin/main men SAKNAR PR #2-mergen. Grenarna delar inte längre en gemensam head. `git pull` ger fel ("divergent branches"). Utan en tydlig reconciliation-strategi är risk för:
- `git push` skriver över PR #2-förenklandet
- `git pull --rebase` tappar lokal historia eller ger massor av konflikter
- Servern kör lokal kod (4 025 rader) som skiljer sig fundamentalt från vad som finns i main

**Åtgärd:** Besluta: Ska origin/main-förenklandet behållas och de 8 lokala commitsarna squash-rebasas ovanpå? Eller är de lokala commitsarna rätt spår och origin/main ska återställas? Gör detta beslutet EXPLICIT i git-historiken med en merge-commit eller rebase — inte tyst.

---

### 10c. `_repair_truncated_json` borttaget utan fallback
Funktionen räddade JSON-svar som LLM trunkerat mitt i en sträng. Nu fallerar `_parse_agent_json` hårt om ett svar trunkeras — agenten rapporteras som `FEL` istället för att räddas. Med en `completeness`-agent nedbantad till `gemini-2.5-flash-lite` med en budgetgräns på 800 tokens (ned från 1 500) är trunkering mer sannolik.

**Åtgärd:** Återinför `_repair_truncated_json` som en separat utility (60 rader), koppla in den i `_parse_agent_json` som sista fallback. Alternativt: öka token-budgeten tillbaka till 1 500.

---

### 10d. `builder_instruktion` och `kontrolleraBuild()` borttagna — loopen är öppnare än förut
Specen inkluderade tidigare en explicit instruktion till byggaren: `"Bygg EXAKT enligt spec, committa och pusha till GitHub, svara kort vad som byggdes."` och det fanns en "Kontrollera"-knapp som auto-hämtade och granskade byggresultatet. Båda är nu borta. Effekten: loopen är ännu mer manuell — byggaren vet inte att hen förväntas pusha till GitHub, och det finns inget sätt att initiera en granskning utan att starta om flödet från Beställ-vyn.

**Åtgärd:** Återinför `builder_instruktion` som en konfigurerbar mall i `settings.json` (kan stängas av per projekt). `kontrolleraBuild()`-knappen bör återinföras som P2-prioritet i byggkön.

---

### 10e. Vag-input-gate borttagen — alla körningar går hela vägen
Kravanalytikern bedömde tidigare om idén var `FÖR_VAGT` och stoppade körningen innan de 20+ specialistagenternas parallell-executor startade. Nu startar alla körningar specialistrundan oavsett input-kvalitet. En användare som skriver "gör appen bättre" startar 25 agenttrådar och kostar pengar utan att producera en användbar spec.

**Åtgärd:** Återinför `underlag`-bedömningen i Kravanalytikern med enkel logik: om `underlag == "FÖR_VAGT"` → returnera early med Promptsmedens motfrågor utan att starta specialistrundan.

---

### 10f. Urvalssteg borttaget — alla fynd läggs direkt i backlog
Beställaren valde tidigare vilka fynd som hörde till ärendet. Nu skriver `if is_review_mode and backlog_result.get("items"):` direkt till `backlog.json` utan urval. Vid en granskning av en stor kodbas kan 15–20 fynd hamna i backloggen automatiskt — varav hälften kanske är false positives eller irrelevanta för nuvarande sprint.

**Åtgärd:** Återinför urvalssteget som ett valfritt steg (toggle i UI — "Välj fynd manuellt" on/off). Default off för att behålla den enklare flödet, men möjligheten bör finnas.

---

## 11. Prioriterad åtgärdslista — vad vi promptar fram

### Prioritet 1 — Säkerhet och stabilitet (gör nu)

| # | Prompt | Berör |
|---|--------|-------|
| P1-a | **Stale "byggs" reset vid startup** — återställ till `kö` + logga, annars blockeras hela kön permanent | `app.py` rad ~32 |
| P1-b | **Hemlighetsvakten som hårt block** — lägg till veto-logik i `/review`-endpointen | `app.py` rad ~3530 |
| P1-c | **Säkerhetsagenter alltid i snabbläge** — lägg till `hemlighetsvakten`, `dataskyddsjuristen` i `_QUICK_AGENT_IDS` | `app.py` rad ~1554 |
| P1-d | **sessions.json paginering** — `/api/sessions?offset=0&limit=50`, läs inte hela filen i minnet | `app.py` rad ~915 |
| P1-e | **_RUN_RESULTS till disk** — skriv stashade resultat till `build_results/run_{id}.json`, rensa vid startup | `app.py` rad ~2948 |
| P1-f | **Simultana granskningar begränsas** — `asyncio.Semaphore(3)` + `HTTP 429` vid överbelastning | `app.py` rad ~2554 |
| P1-g | **Stäng av reload=True** — ändra `uvicorn.run(..., reload=False)` i `__main__`, skapa separat `dev.bat` | `app.py` sista raden |
| P1-h | **Supabase-backup för backlog + build_queue** — lägg till tabeller i schema, synka vid varje write | `supabase_setup.sql` + `app.py` |
| P1-i | **Återlägg `intrim_result*.json` i .gitignore** — borttogs av misstag i PR #2, råa API-svar riskerar committas | `.gitignore` |
| P1-j | **Lös branch-divergens** — besluta om rebase/merge och gör det explicit i git-historiken, annars kör servern fel kod | `git` |
| P1-k | **Dubbel-anrops-skydd på `/review`** — kontrollera `review_started_at` och returnera 409 om granskning redan pågår | `app.py` rad ~2865 |
| P1-l | **Återställ `review_started_at` vid startup** — samma mönster som P1-a för `byggs`-stale | `app.py` rad ~32 |

### Prioritet 2 — Bryt loopen (det saknade steget)

| # | Prompt | Berör |
|---|--------|-------|
| P2-a | **Chatt-UI i Att bygga-vyn** — slide-in panel under byggkö-item, SSE-driven meddelandevy | `index.html` |
| P2-b | **Chatt-backend + SSE** — `/api/chat/session`, `/api/chat/{id}/stream` | `app.py` |
| P2-c | **Auto-dispatch** — `startBuild()` postar job direkt till chattsessionen istället för clipboard | `index.html` |
| P2-d | **GitHub push-endpoint** — `/api/github/push` med GitHub Contents API | `app.py` |
| P2-e | **Auto-callback** — agenten anropar `/result` + `/review` automatiskt när bygget är klart | `app.py` + agent |
| P2-f | **Auto-reloop vid underkänt** — omskriven spec postas tillbaka i chattrutan automatiskt | `app.py` + `index.html` |

### Prioritet 3 — UX-förbättringar

| # | Prompt | Berör |
|---|--------|-------|
| P3-a | **Projektprofiler på servern** — flytta localStorage-projekt till `/api/projects` | `app.py` + `index.html` |
| P3-b | **Sessionsnamn från tolkad_ide** — använd Kravanalytikerns sammanfattning som namn | `app.py` rad ~867 |
| P3-c | **Spec-versionshistorik i UI** — "📜 Versioner"-knapp på byggkö-kort | `index.html` |
| P3-d | **Fas-gruppvy** — kollapsbara fas-grupper med samlad progress i byggkön | `index.html` |
| P3-e | **Tombstone-komprimering vid startup** — rensa deleted_at-items äldre än 30 dagar ur build_queue + backlog | `app.py` rad ~32 |
| P3-f | **Kostnadsdashboard** — sparkline + totalsumma i historikfliken | `app.py` + `index.html` |
| P3-g | **CI-gate med e2e_test.py** — GitHub Actions-workflow på push till main + `.gitignore` för testresultatfiler | `.github/workflows/` |
| P3-h | **Historikpanel: visa totalt antal + sök** — "Visar 50 av N" + klient-sida sökfält | `index.html` |
| P3-i | **openVerifyFix auto-hämtar kod** — hämta från GitHub automatiskt istället för att läsa tom codeInput | `index.html` |
| P3-j | **push_to_github.py läser identitet från settings.json** — ta bort hårdkodad e-post/namn | `push_to_github.py` |
| P3-k | **start_background.vbs dynamisk sökväg** — beräkna path relativt scriptets egen plats | `start_background.vbs` |
| P3-l | **Synka launch.json port med app.py** — ändra 8021 → 8001 (eller en delad konstant) | `.claude/launch.json` |
| P3-m | **Återinför `_repair_truncated_json`** — 60 rader, koppla in i `_parse_agent_json` som sista fallback | `app.py` |
| P3-n | **Återinför vag-input-gate** — `underlag == "FÖR_VAGT"` → early return med motfrågor, ingen specialistrunda | `app.py` |
| P3-o | **Återinför `builder_instruktion` som mall** — konfigurerbar sträng i settings.json, appended på spec | `app.py` + `settings.json` |
| P3-p | **Återinför urvalssteg som opt-in toggle** — "Välj fynd manuellt"-switch i UI, default av | `index.html` |
| P3-q | **GitHub-filhämtning i batchar** — max 10 parallella anrop + sleep(0.5) + varning om >20% None | `app.py` rad ~3183 |
| P3-r | **Återinför `kontrolleraBuild()`** — "🔍 Hämta från GitHub & granska"-knapp vid sidan om inklistrings-modalen | `index.html` |
| P3-s | **Fixa `__import__("httpx")`** — byt till direkt `httpx.get(...)` på rad 3119 och 3158 | `app.py` |
| P3-t | **load_settings() under lock** — linda cache-läsning och skrivning i `_settings_lock` | `app.py` rad ~96 |
| P3-u | **Gitignore `e2e_test.py`** — eller flytta till `.github/tests/` och koppla till CI | `.gitignore` |

---

## 13. Nya fynd — iteration 7 (djupdyk i sessions, kost och klienthantering)

### 13a. `_local_save()` är dead code med vilseledande docstring
Funktionen definieras på rad 617 med docstringen `"Atomic-safe write"` men använder `write_text()` direkt — INTE `_atomic_write()`. Viktigare: den anropas **aldrig** någonstans i koden. `save_session()` använder `_local_update()`, delete använder `_local_delete()`. Funktionen är ett kvarlämnat artefakt och docstringen är tekniskt falsk.

**Åtgärd:** Ta bort `_local_save()` helt. Om en bulk-write-funktion behövs — skapa en ny som faktiskt kallar `_atomic_write()`.

---

### 13b. `_local_load()` kallas utan lock i `list_sessions()` och `get_session()`
Alla skrivfunktioner (`_local_update`, `_local_delete`, `_migrate_sessions`) håller `_sessions_lock`. Men `list_sessions()` och `get_session()` anropar `_local_load()` direkt utan låset. Under en pågående granskning (många `save_session()`-anrop) kan en `GET /api/sessions`-request råka läsa filen mitt i ett skrivfönster. Eftersom `_atomic_write()` gör temp→replace är risken liten men reell på Windows där file-rename inte är garanterat atomärt.

**Åtgärd:** Linda `_local_load()`-anropen i `list_sessions()` och `get_session()` i `with _sessions_lock:`.

---

### 13c. Modellsträngformat-inkonsekvens — `claude-sonnet-4-6` vs `claude-sonnet-4.6`
`_MODEL_PRICES` (rad 167) indexeras med `"anthropic/claude-sonnet-4.6"` (punkt). Defaultinställningen i `load_settings()` returnerar `"claude-sonnet-4-6"` (bindestreck, utan prefix). `_cost_usd("claude-sonnet-4-6", ...)` returnerar `None` — kosten rapporteras som `None` för Anthropic-direktanrop. Dessutom skiljer sig `PROMPT_SMITH`'s `model`-fält (`claude-sonnet-4-6`) från `_DEFAULT_AGENT_MODELS["prompt_smith"]` (`anthropic/claude-sonnet-4.6`) — två olika strängar för samma modell.

**Åtgärd:** Standardisera alla modellsträngar till OpenRouter-format (`provider/model-version` med punkt). Lägg till `"anthropic/claude-sonnet-4-6"` som alias i `_MODEL_PRICES` eller normalisera i `_cost_usd()`.

---

### 13d. `/api/health` skapar ny OpenAI-klient vid varje anrop
`health_check()` konstruerar `_openai.OpenAI(...)` inline istället för att anropa `get_openrouter_client()`. Varje hälsokontroll skapar en ny HTTP connection pool som aldrig stängs. Vid frekvent klick på "Testa anslutning" läcker minnesobjekt.

**Åtgärd:** Byt ut den inline-skapade klienten i `health_check()` mot `get_openrouter_client()`.

---

## 12. Nya fynd — iteration 6 (origin/main djupdyk)

### 12a. `/api/build-queue/{id}/review` — inget skydd mot dubbel-anrop (KRITISK)
`review_started_at` sätts under lock när en granskning startar, men **kontrolleras aldrig** i en `if`-check innan körningen påbörjas. Två snabba klick på "Granska & verifiera" (eller en automatisk retry vid nätverksproblem) startar två parallella fullständiga granskningsrundar för samma item — vardera ~25 agenter, 2–5 min, ~$0.10–0.20. Slutresultatet skrivs av den som landar sist och det finns ingen garanti om vilken som vinner.

**Åtgärd:** Lägg till i `build_queue_review`: `if item.get("review_started_at"): return JSONResponse({"error": "Granskning pågår redan..."}, 409)` direkt efter att item hämtats.

---

### 12b. 80 GitHub-filer hämtas parallellt utan rate-limiting
`asyncio.gather(*[fetch_file(f) for f in selected])` skickar upp till 80 simultana HTTP-anrop mot GitHub Contents API. GitHub har en outtalad sekundär rate limit (~100 req/10s per token) — vid större repos kan detta ge 429-svar. `fetch_file` returnerar tyst `None` vid alla fel (`except Exception: return None`). Resultatet: en granskning av en stor repo kan starta med 20–40 tomma filer utan varning till användaren.

**Åtgärd:** Kör filhämtningarna i batchar om 10 (`asyncio.gather` per batch, `asyncio.sleep(0.5)` mellan batchar). Räkna `None`-svar och returnera en varning om >20% av filerna misslyckades.

---

### 12c. `__import__("httpx")` i GitHub-fetch trots modul-nivå import
Rad 3119 och 3158 använder `lambda: __import__("httpx").get(...)` trots att `import httpx` finns på rad 16. Alla andra HTTP-anrop i filen (rad 2998, 3027, 3051, 3312, 3357) använder `httpx` direkt. Inkonsistensen är förvirrande och kan tyda på att dessa lambdas kopierades från ett annat sammanhang.

**Åtgärd:** Ersätt `__import__("httpx").get(...)` med `httpx.get(...)` på rad 3119 och 3158.

---

### 12d. `review_started_at` rensas inte vid serveromstart
Liknar P1-a (`byggs`-stale): om servern startar om medan `build_queue_review` körs förblir `review_started_at` satt. `startup()` återställer inte detta fält. Posten fastnar i ett halvt "granskas"-tillstånd. Utan fyndet 12a fixat förvärras detta av att nästa anrop också blockeras om vi lägger till skyddet.

**Åtgärd:** I `startup()` — återställ `review_started_at = None` på alla items där fältet är satt (samma mönster som P1-a-åtgärden för `byggs`).

---

### 12e. `load_settings()` läser cache utan lock
`save_settings()` skyddar skrivningen med `_settings_lock`, men `load_settings()` läser och uppdaterar `_settings_cache` *utanför* låset. Med 80 worker-trådar kan en tråd läsa `mtime`, en annan uppdatera `data`, och den första tråden använda gammal data med ny mtime. Liten risk men tekniskt en data race.

**Åtgärd:** Linda `load_settings()`-cacheläsningen och skrivningen i `_settings_lock`. Alternativt: byt till en `threading.local()`-baserad cache.

---

### 12f. `kontrolleraBuild()` borttagen men backend-endpointen finns kvar — UX-glapp
`/api/build-queue/{id}/review` existerar i origin/main och är fullt funktionell, men `kontrolleraBuild()` (auto-hämtning från GitHub + anrop till endpointen) togs bort i PR #2. Det enda sättet att trigga granskningen är nu via "✅ Klar? Klistra in resultatet"-modalen som kräver manuell inklistring. Auto-flödet (hämta senaste commit → granska automatiskt) är borttaget i UI men inte i API.

**Åtgärd:** Återinför `kontrolleraBuild()` som en knapp vid sidan om "Klistra in"-modalen: `"🔍 Hämta från GitHub & granska"`. Triggar `fetchActiveProjectCode()` → POST `/api/build-queue/{id}/review`.

---

### 12g. `e2e_test.py` är inte gitignorerad
`e2e_test.py` kör mot produktionsservern (localhost:8001), innehåller 700s timeouts och 460k-teckens stresstest-payloads. Den är inte i `.gitignore`. `ai_eval_results.json` är gitignorerat men `e2e_test.py` är en testfil som kan ändras per test-run och aldrig borde vara en del av codebasen utan en CI-pipeline.

**Åtgärd:** Lägg `e2e_test.py` i `.gitignore` om den inte ska vara del av projektet. Alternativt: flytta den till `.github/tests/` och koppla den till ett GitHub Actions-workflow (P3-g).

---

### Prioritet 4 — Framtida

| # | Prompt | Berör |
|---|--------|-------|
| P4-a | **Baslinjegranskaren** — ny agent som kontrollerar om idén redan finns i repot | `app.py` |
| P4-b | **GitHub inbound webhook** — `/api/webhook/github` triggar automatisk granskning vid push | `app.py` |
| P4-c | **Visual QA med auto-screenshot** — Playwright headless-screenshot i bygg-loopen | `app.py` |
| P4-d | **Enkel autentisering** — statisk Bearer-token på alla `/api/*`-endpoints | `app.py` |
| P4-e | **Ta bort `/api/version` dead code** — eller implementera live-reload ordentligt | `app.py` |
| P4-f | **Ta bort `_local_save()` dead code** — vilseledande docstring + aldrig anropad | `app.py` rad ~617 |
| P4-g | **Fixa lock i `list_sessions()`/`get_session()`** — linda `_local_load()` i `_sessions_lock` | `app.py` rad ~806, ~833 |
| P4-h | **Normalisera modellsträngar** — standardisera till `provider/model.version`-format i hela koden | `app.py` |
| P4-i | **Hälsokontroll återanvänd cached klient** — byt inline `OpenAI(...)` mot `get_openrouter_client()` | `app.py` rad ~3287 |
