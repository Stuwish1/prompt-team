# BUILD TASKS — Prompt Team
*Varje task nedan är fristående och kan kopieras direkt till en byggare.*
*Senast uppdaterad: 2026-06-10 | Baserad på origin/main `3654bd7`*

---

## PRIORITET 1 — Kritiska stabilitetsproblem (gör nu)

---

### P1-A · Återställ stale `byggs`-items vid serveromstart

**Filer:** `app.py`
**Rader:** `startup()`-funktionen (~rad 31–33)

**Problem:**
`startup()` kör bara `_migrate_sessions()`. Om servern startar om medan ett bygge pågår fastnar itemet i status `"byggs"` för evigt. WIP-limiten tillåter bara ett aktivt bygge per projekt — hela byggkön är permanent blockerad utan förklaring.

**Gör så här:**
```python
@app.on_event("startup")
async def startup():
    _migrate_sessions()
    # Återställ stale byggs-items
    with _queue_lock:
        items = _queue_load()
        reset = 0
        for item in items:
            if item.get("status") == "byggs" and not item.get("deleted_at"):
                item["status"] = "kö"
                _queue_log(item, "reset_after_restart", "Servern startade om under ett aktivt bygge")
                reset += 1
        if reset:
            _queue_write(items)
            logger.info("Startup: återställde %d stale byggs-items till kö", reset)
    # Återställ stale review_started_at
    with _queue_lock:
        items = _queue_load()
        for item in items:
            if item.get("review_started_at"):
                item["review_started_at"] = None
        _queue_write(items)
```

**Acceptanskriterier:**
- Ett item med `status=byggs` vid omstart återfår `status=kö`
- Loggmeddelande skrivs för varje återställt item
- `review_started_at` rensas på alla items vid startup

---

### P1-B · Hemlighetsvakten som hårt block

**Filer:** `app.py`
**Rader:** `/api/review`-endpointen, efter att alla agentresultat samlats (~rad 2500+)

**Problem:**
`hemlighetsvakten`-agenten flaggar hårdkodade hemligheter (API-nycklar, lösenord) men resultatet behandlas bara som ett vanligt fynd. Det finns ingen logik som STOPPAR en spec från att skapas om hemliga strängar hittades i inputen.

**Gör så här:**
Lägg till direkt efter `results` samlats i `/api/review`:
```python
secrets_agent = next((r for r in results if r.get("id") == "hemlighetsvakten"), None)
if secrets_agent and secrets_agent.get("status") == "UNDERKÄND":
    critical = [f for f in secrets_agent.get("findings", [])
                if any(kw in f.lower() for kw in ("api key", "api-nyckel", "lösenord", "password", "secret", "token"))]
    if critical:
        return JSONResponse({
            "error": "Körningen stoppades: Hemlighetsvakten hittade potentiella hemligheter i koden. "
                     "Ta bort alla hårdkodade nycklar och lösenord innan du kör igen.",
            "findings": critical[:5]
        }, status_code=400)
```

**Acceptanskriterier:**
- En granskning med hårdkodad API-nyckel returnerar HTTP 400 med tydligt felmeddelande
- En ren körning påverkas inte

---

### P1-C · Säkerhetsagenter alltid i snabbläge

**Filer:** `app.py`
**Rader:** `_QUICK_AGENT_IDS` (~rad 1438)

**Problem:**
```python
_QUICK_AGENT_IDS = {"architecture", "security", "ux", "database", "api",
                    "error_handling", "edge_case", "visual_qa", "rotorsak"}
```
`hemlighetsvakten` och `dataskyddsjuristen` saknas. I snabbläget (depth=snabb) körs aldrig dessa agenter — en snabb körning kan godkänna kod med hemligheter eller GDPR-brott.

**Gör så här:**
```python
_QUICK_AGENT_IDS = {"architecture", "security", "ux", "database", "api",
                    "error_handling", "edge_case", "visual_qa", "rotorsak",
                    "hemlighetsvakten", "dataskyddsjuristen"}
```

**Acceptanskriterier:**
- `depth="snabb"` inkluderar `hemlighetsvakten` och `dataskyddsjuristen`

---

### P1-D · Sessions-paginering — läs inte hela filen i minnet

**Filer:** `app.py`
**Rader:** `list_sessions()` (~rad 803), `GET /api/sessions`-endpointen

**Problem:**
`list_sessions()` läser in hela `sessions.json` (växer obegränsat) och returnerar bara `[:50]`. Vid 1000+ sessioner läses 4–40 MB in vid varje sidladdning.

**Gör så här:**
Lägg till `offset`-stöd i `list_sessions()`:
```python
def list_sessions(project_id: str = "", offset: int = 0, limit: int = 50) -> dict:
    try:
        data = _local_load()
        sessions = [...]  # befintlig filtrering
        sessions.sort(key=lambda x: x["created_at"], reverse=True)
        total = len(sessions)
        return {"items": sessions[offset:offset+limit], "total": total}
    except Exception:
        return {"items": [], "total": 0}
```
Uppdatera `GET /api/sessions` att acceptera `?offset=0&limit=50` och returnera `{"items": [...], "total": N}`.
Uppdatera `loadHistory()` i `index.html` att visa `"Visar 50 av N"` och en "Ladda fler"-knapp.

**Acceptanskriterier:**
- `GET /api/sessions?offset=0&limit=50` returnerar `{items, total}`
- `GET /api/sessions?offset=50&limit=50` returnerar nästa batch
- Frontend visar "Visar X av N totalt" under listan

---

### P1-E · `_RUN_RESULTS` till disk

**Filer:** `app.py`
**Rader:** `_stash_run_result()` (~rad 2579), `startup()`

**Problem:**
Granskningsresultat cachas i `_RUN_RESULTS` in-memory med 30 min TTL. Vid serveromstart försvinner alla pågående körningars resultat — frontenden får aldrig svaret och visar en tomruta.

**Gör så här:**
```python
BUILD_RESULTS_DIR.mkdir(exist_ok=True)

def _stash_run_result(run_id: str, payload: dict):
    if not run_id:
        return
    # Skriv till disk
    result_file = BUILD_RESULTS_DIR / f"run_{run_id}.json"
    result_file.write_text(json.dumps({"ts": datetime.now().timestamp(), "data": payload},
                           ensure_ascii=False), encoding="utf-8")
    # Behåll in-memory för snabb åtkomst
    now = datetime.now().timestamp()
    with _run_results_lock:
        _RUN_RESULTS[run_id] = {"ts": now, "data": payload}
        for k in [k for k, v in _RUN_RESULTS.items() if now - v["ts"] > 1800]:
            del _RUN_RESULTS[k]

def _get_run_result(run_id: str):
    with _run_results_lock:
        entry = _RUN_RESULTS.get(run_id)
    if entry:
        return entry["data"]
    # Fallback till disk
    result_file = BUILD_RESULTS_DIR / f"run_{run_id}.json"
    if result_file.exists():
        try:
            obj = json.loads(result_file.read_text(encoding="utf-8"))
            if datetime.now().timestamp() - obj["ts"] < 1800:
                return obj["data"]
        except Exception:
            pass
    return None
```
Städa gamla `run_*.json` i `startup()` (äldre än 30 min).

**Acceptanskriterier:**
- Ett pågående resultat överlever en serveromstart
- `run_*.json`-filer äldre än 30 min rensas vid startup

---

### P1-F · Begränsa simultana granskningar

**Filer:** `app.py`
**Rader:** Öppningen av `/api/review`-endpointen (~rad 2275)

**Problem:**
Ingen semaphore eller rate-limit. Dubbel-klick eller parallella användare kan starta 3–5 granskningar simultant = 75–125 agenttrådar mot en pool av 80 → timeouts.

**Gör så här:**
```python
_review_semaphore = asyncio.Semaphore(3)

@app.post("/api/review")
async def review(payload: dict):
    if _review_semaphore.locked() and _review_semaphore._value == 0:
        return JSONResponse(
            {"error": "Tre granskningar pågår redan — vänta en stund och försök igen."},
            status_code=429
        )
    async with _review_semaphore:
        # ... befintlig kod ...
```

**Acceptanskriterier:**
- Fyra simultana POST `/api/review` → den fjärde får HTTP 429 med tydligt meddelande
- Tre simultana körningar fungerar normalt

---

### P1-G · Stäng av `reload=True` i produktion

**Filer:** `app.py`
**Rader:** Sista raden i filen (~rad 3450)

**Problem:**
```python
uvicorn.run("app:app", host="127.0.0.1", port=8001, reload=True)
```
`reload=True` startar om servern automatiskt vid varje filändring. En agentkörning som skriver till en `.py`-fil dödar alla pågående granskningar och tappar `_RUN_RESULTS`.

**Gör så här:**
```python
if __name__ == "__main__":
    import sys
    dev_mode = "--dev" in sys.argv
    uvicorn.run("app:app", host="127.0.0.1", port=8001, reload=dev_mode)
```
Skapa `dev.bat`:
```bat
python app.py --dev
```
Uppdatera `start.bat` till att INTE skicka `--dev`.

**Acceptanskriterier:**
- `python app.py` startar utan reload
- `python app.py --dev` startar med reload
- `start.bat` startar utan reload

---

### P1-H · Supabase-backup för backlog och build_queue

**Filer:** `supabase_setup.sql`, `app.py`

**Problem:**
`backlog.json` och `build_queue.json` har ingen molnbackup. Maskinhaveri = total dataförlust.

**Gör så här — del 1, SQL:**
Lägg till i `supabase_setup.sql`:
```sql
-- Migration v3
INSERT INTO schema_migrations(version) VALUES (3) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS backlog_items (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL,
    deleted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS build_queue_items (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    data JSONB NOT NULL,
    deleted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```
Uppdatera `SUPABASE_SCHEMA_VERSION = 3`.

**Gör så här — del 2, app.py:**
Lägg till asynkron best-effort backup i `_queue_write()` och `backlog`-skrivoperationer:
```python
def _sync_to_supabase_async(table: str, item: dict):
    """Fire-and-forget Supabase upsert — missar OK, lokal fil är primär."""
    if not _sb_available():
        return
    try:
        httpx.post(_sb_url(table), headers=_sb_headers(),
                   json={"id": item["id"], "project_id": item.get("project_id",""),
                         "data": item, "deleted_at": item.get("deleted_at"),
                         "updated_at": datetime.now().isoformat()},
                   timeout=5.0)
    except Exception:
        pass
```

**Acceptanskriterier:**
- `supabase_setup.sql` skapar `backlog_items` och `build_queue_items`
- Skrivoperationer triggar en fire-and-forget upsert till Supabase
- `SUPABASE_SCHEMA_VERSION` är 3 och health-checken varnar om databasen är på v2

---

### P1-I · Återlägg `intrim_result*.json` i `.gitignore`

**Filer:** `.gitignore`

**Problem:**
PR #2 raderade glob-posten `intrim_result*.json` ur `.gitignore`. Råa API-testsvar (inkl. fullt promptinnehåll) riskerar att committas.

**Gör så här:**
Lägg till i `.gitignore`:
```
intrim_result*.json
e2e_test_results*.json
```

**Acceptanskriterier:**
- `git status` visar inte `intrim_result.json` som untracked/modified

---

### P1-J · Lös branch-divergens

**Filer:** git-historik

**Problem:**
Lokal branch är 8 commits FÖRE origin/main men saknar PR #2-mergen. `git pull` ger fel. Servern och repot kör olika versioner av koden.

**Beslut krävs av Stiven:** Vilket spår ska behållas?
- **Alt A:** Behåll origin/main (förenklade versionen). Rebasa de 8 lokala commitsarna ovanpå origin/main och lös konflikter.
- **Alt B:** Behåll lokal kod (4 025-radersversionen). Öppna en ny PR som reverserar PR #2.

```bash
# Alt A:
git rebase origin/main
# Lös konflikter → git add → git rebase --continue
git push --force-with-lease
```

**Acceptanskriterier:**
- `git log --oneline origin/main..HEAD` visar 0 commits
- `git log --oneline HEAD..origin/main` visar 0 commits

---

### P1-L · `get_backlog()` läser utan lås — race condition (KRITISK)

**Filer:** `app.py`
**Rader:** `get_backlog()` (~rad 2601–2603)

**Problem:**
`GET /api/backlog` anropar `_backlog_load()` utan `_backlog_lock`. Alla skrivoperationer (`backlog_add_items`, `update_backlog_item`) hålls under `_backlog_lock`. Under en aktiv granskningskörning kan `run_backlog_agent` skriva till `backlog.json` samtidigt som frontend läser → delvis skriven JSON läses in → API returnerar korrupt data. Vid hög last med parallella granskningar inträffar detta rutinmässigt.

**Gör så här:**
```python
@app.get("/api/backlog")
async def get_backlog(project_id: str = ""):
    with _backlog_lock:
        items = _backlog_load()
    if project_id:
        items = [i for i in items if i.get("project_id") == project_id]
    ...
```

**Acceptanskriterier:**
- `GET /api/backlog` håller `_backlog_lock` under läsningen
- Parallella granskningar och läsningar krockar inte

---

### P1-M · `PATCH /api/build-queue/{id}` saknar storleksgräns på `spec_markdown`

**Filer:** `app.py`
**Rader:** `patch_build_queue()` (~rad 460–480)

**Problem:**
`item["spec_markdown"] = payload["spec_markdown"]` utan längdbegränsning. En spec_markdown på 50 MB skrivs in i `build_queue.json` och hela filen läses vid varje queue-operation under `_queue_lock` → server fryser.

**Gör så här:**
```python
if "spec_markdown" in payload:
    val = str(payload["spec_markdown"])
    if len(val) > 100_000:
        return JSONResponse({"error": "spec_markdown överstiger 100 000 tecken."}, status_code=400)
    item["spec_markdown"] = val
```

**Acceptanskriterier:**
- PATCH med spec_markdown > 100 000 tecken returnerar HTTP 400
- Normal spec (< 10 000 tecken) passerar

---

### P1-N · `POST /api/build-queue` accepterar tom `project_id`

**Filer:** `app.py`
**Rader:** `POST /api/build-queue`-endpointen (~rad 444–454)

**Problem:**
`project_id` valideras inte. Items med `project_id=""` visas i alla projektvyer och kan inte filtreras bort utan manuell patching.

**Gör så här:**
```python
project_id = (payload.get("project_id") or "").strip()
if not project_id:
    return JSONResponse({"error": "project_id krävs."}, status_code=400)
```

**Acceptanskriterier:**
- POST utan `project_id` (eller tomt) returnerar HTTP 400
- POST med giltig `project_id` fungerar som tidigare

---

### P1-K · Dubbel-anrops-skydd på `/api/build-queue/{id}/review`

**Filer:** `app.py`
**Rader:** `build_queue_review()` (~rad 2865)

**Problem:**
`review_started_at` sätts men kontrolleras aldrig. Två snabba klick startar två parallella fullgranskning-rundar (~25 agenter var, $0.10–0.20 vardera).

**Gör så här:**
Lägg till direkt efter item hämtats:
```python
if item.get("review_started_at"):
    return JSONResponse(
        {"error": "En granskning pågår redan för detta bygge. Vänta tills den är klar."},
        status_code=409
    )
```

**Acceptanskriterier:**
- Två snabba POST till samma `/review` → det andra anropet returnerar HTTP 409
- En granskning som slutförts normalt blockerar inte nästa anrop (review_started_at=None)

---

---

### P1-O · `GET /api/build-queue` och `advance_build_queue()` läser utan lås

**Filer:** `app.py`
**Rader:** `get_build_queue()` (~rad 437), `advance_build_queue()` (~rad 591)

**Problem:**
Båda anropar `_queue_load()` utan `_queue_lock`. Under en aktiv `/send`- eller `/patch`-operation kan en parallell GET läsa delvis skriven queue-fil. `advance_build_queue` driver "Bygg nästa"-knappen — stale läsning kan returnera ett item som precis satts till `byggs`.

**Gör så här:**
```python
@app.get("/api/build-queue")
async def get_build_queue(project_id: str = ""):
    with _queue_lock:
        items = _queue_load()
    if project_id:
        items = [i for i in items if i.get("project_id") == project_id]
    items = [i for i in items if not i.get("deleted_at")]
    items.sort(key=lambda i: i.get("position", 0))
    return {"items": items}

@app.post("/api/build-queue/advance")
async def advance_build_queue(project_id: str = ""):
    with _queue_lock:
        items = _queue_load()
    items = [i for i in items if i.get("project_id") == project_id and not i.get("deleted_at")]
    if any(i.get("status") == "byggs" for i in items):
        return {"next_item": None, "reason": "Ett bygge pågår redan."}
    queued = sorted([i for i in items if i.get("status") == "kö"],
                    key=lambda i: i.get("position", 0))
    return {"next_item": queued[0] if queued else None}
```

**Acceptanskriterier:**
- Båda endpoints håller `_queue_lock` under läsningen
- Inga race conditions med parallella `/send`- eller `/patch`-anrop

---

### P1-P · `build_queue_review()` sätter `review_started_at` för sent — TOCTOU

**Filer:** `app.py`
**Rader:** `build_queue_review()` (~rad 2865–2900)

**Problem:**
`review_started_at` sätts EFTER att agentrundan startat (2871: item läses utan lock → ~2900: lock tas och `review_started_at` sätts). Ett andra anrop som kommer in under de 3–10 minuter agenterna kör ser `review_started_at=None` och startar en andra parallell granskning. Båda resultaten skriver över `last_verdict`.

**Gör så här — sätt flaggan INNAN agenter startar:**
```python
@app.post("/api/build-queue/{item_id}/review")
async def build_queue_review(item_id: str, payload: dict):
    # Läs, validera och sätt review_started_at — allt under lock
    with _queue_lock:
        items = _queue_load()
        item = next((i for i in items if i.get("id") == item_id and not i.get("deleted_at")), None)
        if not item:
            return JSONResponse({"error": "Item hittades inte."}, status_code=404)
        if item.get("review_started_at"):
            return JSONResponse(
                {"error": "En granskning pågår redan för detta item."},
                status_code=409
            )
        item["review_started_at"] = datetime.now().isoformat(timespec="seconds")
        _queue_write(items)
    # Hädanefter: parallella anrop blockeras av review_started_at-checken ovan
    # ... resten av funktionen oförändrad, ta bort det gamla review_started_at-blocket längre ned ...
```
Ta bort det befintliga blocket som sätter `review_started_at` längre ned i funktionen.

**Acceptanskriterier:**
- Två nästan-simultana POST till `/review` → det andra returnerar HTTP 409
- `review_started_at` sätts inom millisekunder efter anropet, inte efter 3–10 min agentkörning

---

### P1-Q · `backlog_to_spec()` och `backlog_verify_fix()` läser utan lås

**Filer:** `app.py`
**Rader:** `backlog_to_spec()` (~rad 2675), `backlog_verify_fix()` (~rad 2791)

**Problem:**
Båda anropar `_backlog_load()` utan `_backlog_lock` för det initiala item-uppslaget. Om `run_backlog_agent` skriver till `backlog.json` samtidigt kan stale `finding`/`suggestion` användas som seed för Promptsmeden — specen genereras på fel underlag.

**Gör så här (samma mönster som P1-L):**
```python
# I backlog_to_spec():
with _backlog_lock:
    items = _backlog_load()
item = next((i for i in items if i.get("id") == item_id), None)

# I backlog_verify_fix():
with _backlog_lock:
    items = _backlog_load()
item = next((i for i in items if i.get("id") == item_id), None)
```

**Acceptanskriterier:**
- Initialt uppslag håller `_backlog_lock`
- Ingen ändring i funktionernas övriga logik


## PRIORITET 2 — Bryt den manuella loopen

---

### P2-A · Chatt-UI i Att Bygga-vyn

**Filer:** `index.html`

**Problem:**
Det enda sättet att skicka en spec till en byggare är `navigator.clipboard.writeText(spec)`. Ingen kommunikationskanal existerar i systemet.

**Gör så här:**
Lägg till en slide-in chattpanel på höger sida om byggkön. Den ska:
1. Visas när ett item expanderas (status=byggs)
2. Innehålla en meddelandehistorik (`<div id="chatMessages">`)
3. Ha ett textfält + Skicka-knapp
4. Visa specarens innehåll som det första meddelandet automatiskt
5. Anropa `POST /api/chat/{queue_item_id}` (implementeras i P2-B)

HTML-struktur (enkel):
```html
<div id="chatPanel" class="chat-panel" style="display:none">
  <div id="chatMessages" class="chat-messages"></div>
  <div class="chat-input-row">
    <textarea id="chatInput" rows="3" placeholder="Skriv till byggaren..."></textarea>
    <button onclick="sendChatMessage()">Skicka</button>
  </div>
</div>
```

**Acceptanskriterier:**
- Panelen visas när ett `byggs`-item expanderas
- Specarens `spec_markdown` visas som första meddelande
- Skicka-knappen anropar backend och lägger till svaret i historiken

---

### P2-B · Chatt-backend + SSE-streaming

**Filer:** `app.py`

**Gör så här:**
```python
_chat_sessions: dict = {}  # item_id → [{"role", "content", "ts"}]

@app.post("/api/chat/{item_id}")
async def chat_message(item_id: str, payload: dict):
    """Lägg till ett meddelande i chatthistoriken för ett byggkö-item."""
    msg = {"role": payload.get("role", "user"),
           "content": payload.get("content", ""),
           "ts": datetime.now().isoformat(timespec="seconds")}
    _chat_sessions.setdefault(item_id, []).append(msg)
    return {"ok": True, "message": msg}

@app.get("/api/chat/{item_id}")
async def get_chat(item_id: str):
    """Hämta all chatthistorik för ett item."""
    return {"messages": _chat_sessions.get(item_id, [])}
```

**Acceptanskriterier:**
- `POST /api/chat/{id}` sparar meddelande och returnerar det
- `GET /api/chat/{id}` returnerar alla meddelanden
- En spec kan hämtas via `GET /api/build-queue/{id}` och postas som första meddelande

---

### P2-C · Auto-dispatch — `startBuild()` postar till chatt

**Filer:** `index.html`
**Rader:** `startBuild()`-funktionen

**Problem:**
```javascript
await navigator.clipboard.writeText(spec);
showToast('📋 Spec kopierad — klistra in i din byggare');
```
Spec kopieras till urklipp. Ingen automation möjlig.

**Gör så här:**
Ersätt clipboard-logiken med:
```javascript
async function startBuild(id, btn) {
  // ... befintlig fetch till /send ...
  const data = await res.json();
  const spec = data.job?.spec_markdown || '';
  // Posta spec som första chattmeddelande
  await fetch('/api/chat/' + id, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ role: 'spec', content: spec })
  });
  // Behåll clipboard-fallback
  await navigator.clipboard.writeText(spec).catch(() => {});
  showToast('▶ Spec skickad till byggaren och kopierad!', 3000);
  openChatPanel(id);
}
```

**Acceptanskriterier:**
- Klick på "Bygg nästa" postar spec till `/api/chat/{id}`
- Chattanelen öppnas automatiskt
- Specen finns fortfarande i urklipp som fallback

---

### P2-D · GitHub push-endpoint

**Filer:** `app.py`

**Gör så här:**
```python
@app.post("/api/github/push")
async def github_push(payload: dict):
    """Skicka en eller flera filer till GitHub via Contents API."""
    repo = payload.get("repo") or load_settings().get("self_repo", "")
    branch = payload.get("branch") or load_settings().get("self_branch", "main")
    files = payload.get("files") or []  # [{"path": str, "content": str}]
    message = payload.get("message", "feat: auto-push från Prompt Team")
    if not repo or not files:
        return JSONResponse({"error": "repo och files krävs"}, status_code=400)
    token = load_settings().get("github_token", "")
    if not token:
        return JSONResponse({"error": "GitHub-token saknas"}, status_code=400)
    # Använd GitHub Contents API för varje fil
    results = []
    for f in files[:20]:
        import base64
        content_b64 = base64.b64encode(f["content"].encode()).decode()
        # Hämta befintlig SHA om filen finns (krävs för update)
        get_url = f"https://api.github.com/repos/{repo}/contents/{f['path']}?ref={branch}"
        get_resp = httpx.get(get_url, headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
        sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None
        put_body = {"message": message, "content": content_b64, "branch": branch}
        if sha:
            put_body["sha"] = sha
        put_url = f"https://api.github.com/repos/{repo}/contents/{f['path']}"
        put_resp = httpx.put(put_url, headers={"Authorization": f"Bearer {token}"},
                             json=put_body, timeout=15.0)
        results.append({"path": f["path"], "ok": put_resp.status_code in (200, 201)})
    return {"ok": all(r["ok"] for r in results), "files": results}
```

**Acceptanskriterier:**
- `POST /api/github/push` med `{repo, files: [{path, content}]}` pushar filerna
- Befintliga filer uppdateras (SHA hämtas automatiskt)
- Nya filer skapas

---

## PRIORITET 3 — UX och driftstabilitet

---

### P3-A · Projektprofiler på servern (flytta från localStorage)

**Filer:** `app.py`, `index.html`

**Problem:**
Alla projekt (`getProjects()`) lagras i `localStorage`. Byt dator → projekt borta.

**Gör så här:**
Skapa `projects.json` (samma mönster som `backlog.json`):
```python
PROJECTS_FILE = BASE_DIR / "projects.json"
_projects_lock = threading.Lock()

@app.get("/api/projects")
async def get_projects():
    ...

@app.post("/api/projects")
async def create_project(payload: dict):
    ...

@app.patch("/api/projects/{project_id}")
async def update_project(project_id: str, payload: dict):
    ...

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    ...
```
Frontend: ersätt `localStorage.getItem(PROJECTS_KEY)` med `fetch('/api/projects')`.
Migration: vid `initProjects()`, om `localStorage` har projekt → posta dem till `/api/projects` och rensa `localStorage`.

**Acceptanskriterier:**
- Projekt överlever byte av webbläsare/maskin
- Befintliga localStorage-projekt migreras automatiskt vid första laddningen
- Alla CRUD-operationer fungerar mot backend

---

### P3-G · CI-gate med GitHub Actions

**Filer:** `.github/workflows/ci.yml` (ny fil)

**Gör så här:**
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - name: Start server
        run: python app.py &
        env:
          OPENROUTER_KEY: ${{ secrets.OPENROUTER_KEY }}
      - name: Wait for server
        run: sleep 5 && curl -f http://localhost:8001/api/health || exit 1
      - name: Run e2e tests
        run: python e2e_test.py
        timeout-minutes: 15
```
Lägg till `requirements.txt` om den saknas.

**Acceptanskriterier:**
- Push till main triggar CI
- En buggig `app.py` (t.ex. SyntaxError) blockerar merge
- CI-status visas på repots startsida

---

### P3-H · Historikpanel: visa totalt antal + sökfält

**Filer:** `index.html`
**Rader:** `loadHistory()`-funktionen och historikpanelens HTML

**Problem:**
50-sessionsgränsen är osynlig. Ingen sökning finns.

**Gör så här:**
1. Uppdatera `loadHistory()` att visa `"Visar 50 av N"` (kräver P1-D backend-ändringen)
2. Lägg till ett sökfält ovanför sessionslistan:
```html
<input id="historySearch" type="search" placeholder="Sök session..." oninput="filterHistory(this.value)">
```
```javascript
let _allSessions = [];
function filterHistory(q) {
  const filtered = q
    ? _allSessions.filter(s => (s.name + s.project_id).toLowerCase().includes(q.toLowerCase()))
    : _allSessions;
  renderSessionList(filtered);
}
```

**Acceptanskriterier:**
- Sökfältet filtrerar listan i realtid
- "Visar 50 av N" visas under listan
- "Ladda fler"-knapp laddar nästa 50

---

### P3-M · Återinför `_repair_truncated_json`

**Filer:** `app.py`
**Rader:** `_parse_agent_json()`-funktionen

**Problem:**
Borttaget i PR #2. `completeness`-agenten kör nu med 800 tokens (ned från 1500) på `gemini-2.5-flash-lite` — trunkering är mer sannolik. JSON-fel = agent rapporteras som FEL.

**Gör så här:**
Lägg till funktionen (60 rader) igen och koppla in den som sista fallback i `_parse_agent_json()`:
```python
def _repair_truncated_json(text: str) -> dict | None:
    """Sista utväg: rädda trunkerad JSON från en provider-stopp mitt i en sträng."""
    for cut in range(len(text), max(len(text) - 2000, 1), -1):
        candidate = text[:cut].rstrip().rstrip(",")
        in_str = False; esc = False; opens = []
        for ch in candidate:
            if esc: esc = False; continue
            if ch == "\\": esc = True
            elif ch == '"': in_str = not in_str
            elif not in_str and ch in "{[": opens.append(ch)
            elif not in_str and ch in "}]":
                if opens: opens.pop()
        repaired = candidate + ('"' if in_str else "")
        repaired += "".join("}" if o == "{" else "]" for o in reversed(opens))
        try:
            obj = json.loads(repaired)
            if isinstance(obj, dict) and obj:
                return obj
        except Exception:
            continue
    return None
```
I `_parse_agent_json()`, efter det andra försöket:
```python
if parsed.get("_error") == "no_json":
    repaired = _repair_truncated_json(raw)
    if repaired:
        repaired.setdefault("findings", [])
        repaired.setdefault("suggestions", [])
        repaired.setdefault("severity", "MEDIUM")
        repaired["findings"].append("[OBS: agentsvaret trunkerades]")
        parsed = repaired
```

**Acceptanskriterier:**
- En truncated JSON-sträng räddas istället för att rapporteras som FEL
- Räddade svar innehåller `[OBS: agentsvaret trunkerades]` i findings

---

### P3-N · Återinför vag-input-gate

**Filer:** `app.py`
**Rader:** Kravanalytikerns svarsparsning i `/api/review`

**Problem:**
Borttaget i PR #2. Alla körningar startar nu specialistrundan oavsett input-kvalitet. "gör appen bättre" startar 25 agenttrådar för ~$0.05.

**Gör så här:**
I `_run_krav()` — om `krav_result.get("underlag") == "FÖR_VAGT"` och `mode == "ny_funktion"`:
```python
if mode == "ny_funktion" and krav_result.get("underlag") == "FÖR_VAGT":
    # Skippa specialistrundan — returnera bara krav + frågor
    smith_result = await loop.run_in_executor(
        executor, run_prompt_smith, input_text, [], model, client, synth_usage, profile
    )
    return {
        "session_id": run_id,
        "results": [],
        "smith": smith_result,
        "krav": krav_result,
        "stats": {"total": 0, "approved": 0, "rejected": 0, "errors": 0},
        "vag_input": True,
    }
```
Kravanalytikern måste instrueras att sätta `underlag: "FÖR_VAGT"` när idén är för oprecis.

**Acceptanskriterier:**
- En mycket vag idé (< 10 ord, inga konkreta krav) returnerar motfrågor utan att starta specialistrundan
- En tydlig idé med minst ett konkret krav kör hela pipelinen

---

### P3-Q · GitHub-filhämtning i batchar

**Filer:** `app.py`
**Rader:** `fetch_file`-loopen i `/api/github/fetch` (~rad 3183)

**Problem:**
80 simultana HTTP-anrop → GitHub sekundär rate limit → tyst `None` per fil → tom granskning utan varning.

**Gör så här:**
```python
BATCH_SIZE = 10
batches = [selected[i:i+BATCH_SIZE] for i in range(0, len(selected), BATCH_SIZE)]
file_results = []
for batch in batches:
    batch_results = await asyncio.gather(*[fetch_file(f) for f in batch])
    file_results.extend(batch_results)
    if len(batches) > 1:
        await asyncio.sleep(0.3)

files = [f for f in file_results if f]
none_count = sum(1 for f in file_results if f is None)
if none_count > len(selected) * 0.2:
    logger.warning("GitHub fetch: %d/%d filer misslyckades — möjlig rate limit", none_count, len(selected))
```
Returnera `"fetch_warnings"` i svaret om none_count > 20%.

**Acceptanskriterier:**
- Filhämtning sker i batchar om 10 med 300ms paus
- Om >20% av filerna returnerar None visas en varning i UI

---

### P3-R · Återinför `kontrolleraBuild()`

**Filer:** `index.html`
**Rader:** `startBuild()`-kortets knappar i Att Bygga-vyn

**Problem:**
`kontrolleraBuild()` togs bort i PR #2 men `/api/build-queue/{id}/review`-endpointen finns kvar. Auto-flödet (hämta senaste commit → granska automatiskt) är borttaget i UI.

**Gör så här:**
Lägg till knapp bredvid "Klistra in resultatet" i `byggs`-status:
```javascript
async function kontrolleraBuild(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⬇️ Hämtar från GitHub...'; }
  try {
    const fetched = await fetchActiveProjectCode();
    if (!fetched?.code?.trim())
      throw new Error('Kunde inte hämta koden — har byggaren pushat?');
    if (btn) btn.textContent = '🔍 Teamet granskar...';
    const res = await fetch('/api/build-queue/' + id + '/review', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ code: fetched.code,
                             profile: { ...(getActiveProject()?.profile || {}), name: getActiveProject()?.name || '' } })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'HTTP ' + res.status);
    showToast(data.new_status === 'klar'
      ? '✅ GODKÄNT — bygget verifierat!'
      : `⚠ UNDERKÄNT — ${(data.verdict?.kvarstaende||[]).length} kvarstående problem`, 6000);
    await loadAttBygga();
  } catch(e) {
    showToast('❌ ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = '🔍 Kontrollera'; }
  }
}
```
Lägg till i `byggs`-kortets knappar:
```html
<button class="btn btn-ghost" onclick="kontrolleraBuild('${it.id}', this)">🔍 Kontrollera mot GitHub</button>
```

**Acceptanskriterier:**
- Knappen hämtar senaste koden från GitHub och triggar `/review`
- Resultatet visas som `klar` eller `behover_dig` på kortet
- Knappen inaktiveras under körning

---

### P3-S · Skärp backlog-dedup i `_is_same_issue()`

**Filer:** `app.py`
**Rader:** `_is_same_issue()` (~rad 311–316)

**Problem:**
Tröskel 0.5 utan minimumkrav på overlap-storlek ger falskt positiva matchningar vid korta token-set. `"status"` och `"status_route"` delar prefix `"statu"` och matchar falskt. Semantiskt identiska issues med olika ordval (`"saknas validering"` vs `"ingen kontroll"`) skapar dubbletter.

**Gör så här (kortsiktig fix):**
```python
def _is_same_issue(a_tokens: set, b_tokens: set) -> bool:
    if not a_tokens or not b_tokens or len(a_tokens) < 2 or len(b_tokens) < 2:
        return False
    inter = len(a_tokens & b_tokens)
    return inter >= 3 and inter / min(len(a    return inter >= 3 and inter / min(len(a_tokens), len(b_tokens)) >= 0.65
```

**Acceptanskriterier:**
- Orelaterade issues med ett gemensamt ord matchas inte som dubbletter
- Uppenbara dubbletter (identisk titel, lätt omformulerad) matchas fortfarande
- Backlog-agentens `"regression": true`-flagga används som primärt filter

---

---

### P3-T · `_progress_set()` kör O(n) GC på varje anrop — flytta till bakgrundsjobb

**Filer:** `app.py`
**Rader:** `_progress_set()` (~rad 2251–2265), `startup()` (~rad 31)

**Problem:**
GC-loopen körs under `_progress_lock` vid varje agentuppdatering. Med 25 agenter × 3 simultana granskningar = 75 GC-loopen hålls lock hårt. `GET /api/progress/{id}` blockeras, vilket fördröjer SSE-polling och gör att UI verkar hängt.

**Gör så här:**
Ta bort GC-koden ur `_progress_set()`:
```python
def _progress_set(run_id: str, **kwargs):
    if not run_id:
        return
    with _progress_lock:
        entry = _progress.setdefault(run_id, {"phase": "start", "agents": {}, "updated": 0})
        agents_update = kwargs.pop("agent", None)
        entry.update(kwargs)
        if agents_update:
            entry["agents"][agents_update[0]] = agents_update[1]
        entry["updated"] = datetime.now().timestamp()
        # GC borttagen — sker nu i bakgrundsjobbet
```

Lägg till bakgrundsjobb och starta i `startup()`:
```python
async def _progress_gc_loop():
    """Städar _progress var 5:e minut istället för vid varje agentanrop."""
    while True:
        await asyncio.sleep(300)
        cutoff = datetime.now().timestamp() - 900
        with _progress_lock:
            stale = [k for k, v in _progress.items() if v.get("updated", 0) < cutoff]
            for k in stale:
                _progress.pop(k, None)
        if stale:
            logger.debug("_progress GC: rensade %d stale entries", len(stale))

@app.on_event("startup")
async def startup():
    _migrate_sessions()
    asyncio.ensure_future(_progress_gc_loop())
    # ... övriga startup-rader ...
```

**Acceptanskriterier:**
- `_progress_set()` håller lock kortast möjliga tid (inga loopar)
- GC körs var 5:e minut och loggar antalet rensade entries
- `GET /api/progress/{id}` svarar snabbt även under hög last



## PRIORITET 4 — Teknisk skuld och framtida features

---

### P4-A · Fixa `__import__("httpx")` → `httpx`

**Filer:** `app.py`
**Rader:** ~3119, ~3158

Ersätt `lambda: __import__("httpx").get(...)` med `lambda: httpx.get(...)`. `httpx` är redan importerat på rad 16.

---

### P4-B · `load_settings()` under lock

**Filer:** `app.py`
**Rader:** `load_settings()` (~rad 96)

Lägg till `_settings_lock` runt cache-läsning och uppdatering för att undvika race condition om settings ändras under en aktiv granskning.

---

### P4-C · Ta bort `_local_save()` dead code

**Filer:** `app.py`
**Rader:** ~617–621

Funktionen anropas aldrig. Ta bort den och dess vilseledande "Atomic-safe"-docstring.

---

### P4-D · Hälsokontroll återanvänd cached klient

**Filer:** `app.py`
**Rader:** `health_check()` (~rad 3280–3295)

Ersätt den inline-skapade `_openai.OpenAI(...)` i `health_check()` med `get_openrouter_client()`.

---

### P4-E · Normalisera modellsträngar

**Filer:** `app.py`

Lägg till aliases i `_MODEL_PRICES`:
```python
_MODEL_PRICES["anthropic/claude-sonnet-4-6"] = _MODEL_PRICES["anthropic/claude-sonnet-4.6"]
_MODEL_PRICES["claude-sonnet-4-6"] = _MODEL_PRICES["anthropic/claude-sonnet-4.6"]
```
Standardisera `PROMPT_SMITH["model"]` till `"anthropic/claude-sonnet-4.6"`.

---

### P4-F · GitHub inbound webhook

**Filer:** `app.py`

```python
@app.post("/api/webhook/github")
async def github_webhook(request: Request):
    """Ta emot GitHub push-events och trigga automatisk kod-granskning."""
    sig = request.headers.get("X-Hub-Signature-256", "")
    body =