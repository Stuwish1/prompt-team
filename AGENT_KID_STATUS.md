# KID-agent Status
**Senast analyserad:** 2026-06-10 · app.py rad 1–4683 · PROJECT_STATUS.md · AGENT_KID_STATUS.md (föregående)

---

## Nya fynd sedan sist

### Pipeline & affärslogik

**1. `review_started_at` läcker — permanent låsning av item (MEDIUM)**
`build_queue_review()` sätter `review_started_at` under lock, men rensar det INTE i dessa early-exit paths:
- **Rad ~4076**: inline result-save (koden i payload) returnerar JSONResponse → funktionen returnerar direkt utan att nolla `review_started_at`
- **Rad ~4083**: `result_ref` saknas → returnerar 409 utan att nolla
Konsekvens: itemet är permanent låst för framtida granskningar tills servern startas om. Startup-rensningen vid rad 54–63 fixar det, men inte under drift.
**Fix:** Lägg till `item["review_started_at"] = None; _queue_write(items)` i båda early-exit paths (kräver att lock återtas).

**2. GitHub webhook triggar fel status-filter (MEDIUM)**
`/api/webhook/github` (rad 4472) söker efter items med `status == "klar"` att re-granska vid push. Items i "klar" är redan godkända och färdiga — det finns ingen logik för att hitta `"byggs"`-items med `result_ref` satt (dvs. byggaren har pushat och väntar på granskning). Push-triggern aktiverar alltså aldrig det avsedda automatiska granskningsflödet.
**Fix:** Filtrera på `status == "byggs" AND result_ref is not None` för att triggra granskning på byggen som faktiskt väntar på det.

**3. Parallella webhook-granskningar saknar throttling (LOW)**
Om flera items är "klar" vid en push skapar webhooket `asyncio.create_task(build_queue_review(...))` för dem alla simultant. P1-F semaphore skyddar `/api/review`-endpoint-anrop, men `build_queue_review` anropar `review()` internt — det är oklart om semaphoren täcker interna anrop. Vid 5+ items kan detta orsaka resurspik.
**Fix:** Bekräfta att `/api/review`-semaphore täcker interna anrop, alternativt lägg en global `asyncio.Semaphore(2)` runt webhook-tasks.

**4. `_chat_sessions` dict obegränsad (LOW)**
Global dict `_chat_sessions` (rad 104) saknar maxstorlek och TTL. Varje chat-session läggs till men rensas aldrig automatiskt. Vid lång drift eller aggressiv användning kan detta växa obegränsat i minnet.
**Fix:** Byt till `collections.OrderedDict` med max 200 sessioner och LRU-eviction, alternativt rensa sessions äldre än 24h i `_progress_gc_loop`.

**5. app.py trunkering-bug troligen åtgärdad (INFO)**
PROJECT_STATUS anger "BUG-KRITISK: app.py trunkerad rad 4676" som öppen. Vid denna analys lästes app.py komplett till rad 4683 utan syntaxfel — filen verkar hel. Kontrollera mot senaste git att buggen faktiskt stängdes, annars ta bort från kö.

---

## Rekommendationer (prioriterade)

1. **Fixa `review_started_at`-läckan** — lägst hängande frukt, konkret bug med tydlig fix (se fynd 1). Utan fix kan items permanent fastna och kräva serveromstart.
2. **Fixa GitHub webhook-filter** — push-triggern fungerar inte alls för det avsedda flödet (se fynd 2). Antingen fixa filtret eller ta bort webhook-funktionen ur UI tills det fungerar.
3. **Begränsa `_chat_sessions`** — riskerar minnesläcka vid långkörning (se fynd 4). Enkel fix.
4. **Bekräfta/stäng app.py-trunkering** — verifiera i git om buggen är stängd och uppdatera PROJECT_STATUS.

---

## Tidigare flaggat (fortfarande relevant)

Alla **TASK-01 till TASK-43** från föregående körning — inga KID_MODE-UX-ändringar är implementerade. Grundproblemet kvarstår: `KID_MODE`-flagg saknas helt i `settings.json`, `app.py` och `index.html`. Teknisk jargong, agentnamn, admin-UI och `push_to_github.bat`-text är fortfarande synliga för alla användare.

**Byggordningen är fortfarande:**
```
TASK-01 (KID_MODE-flagg) → alla övriga TASK-0x–43
TASK-02 (.gitignore)       — oberoende
```

Inget av detta blockerar backend-flödet, men det blockerar att systemet är användbart för målgruppen (barn/icke-tekniska).

---

## Löst sedan sist

- **P1-P: build_queue_review() TOCTOU** — `review_started_at`-guard under lock implementerad. OBS: Fix introducerar ny risk (läcka vid early-exit) — se Nytt fynd 1.
- **P3-T: `_progress_set()` GC** — bakgrundsjobb, godkänd 2026-06-10.
- **P1-A: Stale "byggs"-items** — återställs korrekt vid serveromstart (rad 42–52, verifierat).
- **BUG: app.py SyntaxError rad 4807** — stängd (separat från ny trunkering-note).

---

*Analyserat av: KID-agent (Claude Sonnet 4.6) · Körd automatiskt 2026-06-10*
