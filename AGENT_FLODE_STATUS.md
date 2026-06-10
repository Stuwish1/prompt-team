# Flödesagent Status
**Senast analyserad:** 2026-06-10 (automatisk körning, iteration 15)  
*Baserad på app.py (5248 rader), build_queue.json (65 items), PROJECT_STATUS.md*

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
[8] BYGGE         POST /api/build-queue/{id}/send → auto-dispatch + SSE /api/builder/stream/{id}
      ↓
[9] GRANSKA BYGGE POST /api/build-queue/{id}/review
      ↓
[10] GODKÄNN/OM   klar | behover_dig → blockerar kön
      ↓
[11] CHATT        POST /api/chat → SSE-streaming + tool_use (bash, fil, git)
```

---

## Nya fynd sedan sist

### 1. DB-QUEUE-PERSIST delvis implementerad — `_queue_write()` fortfarande fire-and-forget (LOW)
**Plats:** `app.py` rad 642–649  
**Problem:** Specen (steg 2) krävde att `_queue_write()` ersätter fire-and-forget med ett **synkront** bulk-upsert till Supabase. Aktuell kod skriver fortfarande primärt till fil och kör fire-and-forget per item. Dessutom saknas `_migrate_queue_to_supabase()` (spec steg 3) — den anropas aldrig vid startup.

```python
def _queue_write(items: list) -> None:
    """Caller must hold _queue_lock."""
    tmp = BUILD_QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(...)                       # ← primär skrivning till fil
    tmp.replace(BUILD_QUEUE_FILE)
    for it in items:
        _sync_to_supabase_async(...)          # ← fortfarande fire-and-forget (spec: synkront)
```

**Konsekvens:** Läsvägen fungerar nu korrekt (Supabase primär → fil fallback). Men om Railway startar om och Supabase-synken misslyckades tyst tidigare (nätfel) kan kön vara partiellt inkonsistent. Spec:ens huvud-acceptanskriterium ("GET /api/build-queue returnerar items efter restart") är uppfyllt via läsvägen — allvaret är lägre än ursprungsproblemet.  
**Åtgärd:** Implementera synkront bulk-upsert i `_queue_write()` samt lägg till `_migrate_queue_to_supabase()` i startup, exakt enligt spec (build_queue.json item 6831b647).

---

## Rekommendationer (prioriterade)

1. **[MEDIUM] `_safe_run_cmd` — `shell=True` kvarstår** (rad 4785–4787): whitelist-skyddet minskar risken men eliminerar den inte. FLÖDE-FIX1 (3dbcd620) är lagd i kön — den fixar detta.

2. **[LOW] DB-QUEUE-PERSIST skrivväg + startup-migrering saknas** — se nytt fynd ovan.

3. **[LOW] Semaphore-blockering vid webhook-triggrad granskning** — `build_queue_review()` → `review()` returnerar 429 under hög last → item fastnar i "byggs" utan automatisk retry.

---

## Tidigare flaggat (fortfarande relevant)

### `_safe_run_cmd` — `shell=True` (från iteration 13)
- Funktion rad 4777–4791. WIP-commit och final-commit i `builder_stream` är nu fixade (se "Löst"). `_safe_run_cmd` i sig kvarstår med `shell=True` — FLÖDE-FIX1 i kön åtgärdar detta.

### Semaphore-blockering vid webhook-triggrad granskning (från iteration 12)
- `build_queue_review()` → `review()` returnerar 429 under hög last → item fastnar i "byggs" utan retry.

### Manuellt gap i byggflödet (steg 8)
- SSE-endpoint `/api/builder/stream/{id}` kräver manuell åtgärd efter `ready_to_push`. Ingen automatisk notis till frontend att commit är klart utan att användaren tittar aktivt.

### Projekttillstånd i localStorage
- `project_id` lagras i webbläsarens localStorage. Försvinner vid byte av maskin/incognito. Backend-projektsync saknas.

---

## Löst sedan sist (iteration 14 → 15)

### ✅ Shell injection i WIP-commit + final commit (builder_stream)
Båda git-commit-anropen i `builder_stream` (rad 4991, 5128) kör nu `subprocess.run(["git", "commit", "-m", ...], shell=False)` — injektionsvektorn via `item["title"]` är stängd. AGENT-FIX-3-varianten för dessa specifika platser är bekräftad.

### ✅ Webhook SHA-match träffar aldrig
Rad 4514–4515: jämförelsen är nu `i.get("result_summary", {}).get("commit_sha") == after_sha`. Den felaktiga jämförelsen mot `result_ref` (filnamnsformat) är borta. SHA-match fungerar korrekt om builder rapporterar `commit_sha` via `/result`.

### ✅ DB-QUEUE-PERSIST läsväg
`_queue_load()` (rad 615–640) läser nu från Supabase som primär källa vid Railway-deploy. Fil-fallback kvarstår för lokala miljöer. Spec:ens huvud-acceptanskriterium uppfyllt.

---

## Köstatus just nu (från build_queue.json)

| Status | Antal | Items |
|--------|-------|-------|
| klar   | 62    | Alla historiska byggen |
| byggs  | 1     | CHATBOX-POLISH (eac32328) — aktivt bygge (projekt: main) |
| kö     | 2     | KID-SPRINT1 (220d7a8b) + FLÖDE-FIX1 (3dbcd620) |
| behover_dig | 0 | Ingen grön-gate aktiv |

*OBS: byggs-items i projekten gate-test, fas-test och rewrite-test är testfixtures (CI-data) — de är inte aktiva byggen i produktion.*

---

## Sammanfattning — Flödets mognadsnivå

| Fas | Mognad | Kommentar |
|-----|--------|-----------|
| Granskning (1–4) | 🟢 Hög | Semaphore, recovery, GC — stabilt |
| Urval + planering (5–6) | 🟡 Medel | Fungerar lokalt; Stiven beslutar om branch-divergens (P1-J) |
| Att Bygga-vy (7) | 🟡 Medel | localStorage-beroe