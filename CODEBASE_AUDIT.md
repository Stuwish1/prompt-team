# Codebase Audit — Prompt Team
> **Iteration 6** — 2026-06-10. Läs denna fil INNAN du rör kod.
> Senaste git-kontroll: commit `bfa1f45` är senaste på `feat/agent-audit-export`. Branch är synkad med remote.

---

## Fyra parallella spår — skicka RÄTT fil till rätt roll

| Spår | Dokument | Roll | Fokus |
|------|----------|------|-------|
| **A — Chatbox** | `AGENT_CHATBOX_BUILD.md` | Snickare | SSE-stream, agent-loop, auto-build |
| **B — Stabilitet** | `BUILD_TASKS.md` | Snickare via Projektledare | Kritiska buggar, features, P1–P4 |
| **C — DRY** | `CODEBASE_AUDIT.md` (detta) | Snickare | Koduppstädning R1–R6 |
| **Roller** | `PROJEKTLEDARE_INSTRUKTION.md` + `SNICKARE_INSTRUKTION.md` | Agenter | Vem gör vad |

> **Hur agentsystemet fungerar:** Projektledaren läser `BUILD_TASKS.md`, lägger tasks i kön
> via `/api/build-queue`. Snickaren plockar upp `byggs`-items och rapporterar i `BUILD_RESULT.md`.

---

## Git-status

| | |
|---|---|
| Senaste commit | `bfa1f45` — per-projekt agentinst., secrets-blockering, nya agenter |
| Branch | `feat/agent-audit-export`, 9 commits före `origin/main` |
| Kvarstår | `origin/main` har `3654bd7` (PR #2) som saknas lokalt — se P1-J |
| Unstaged | `AGENT_CHATBOX_BUILD.md` (+329 rader), `BUILD_TASKS.md` (+75 rader), `ARKITEKTUR_ANALYS.md`, `BYGG_TASKS.md`, `index.html`, `.gitignore` |
| Nya otrackade | `PROJEKTLEDARE_INSTRUKTION.md`, `SNICKARE_INSTRUKTION.md`, `intrim_result*.json` |

---

## Filkarta

| Fil | Rader | Roll |
|---|---|---|
| `app.py` | ~4 387 | Hela backenden — syntax OK (verifierat) |
| `index.html` | **4 121** | Frontend — **nu komplett**, slutar med `</html>` ✅ |
| `AGENT_CHATBOX_BUILD.md` | ~2 817 | Spår A — chatbox, TASK-00 till TASK-12 + iteration 9-fynd |
| `BUILD_TASKS.md` | ~969 | Spår B — P1-P4 (nu P1-N som senaste) |
| `ARKITEKTUR_ANALYS.md` | ~850 | Underlag — 18+ arkitekturfynd |
| `BYGG_TASKS.md` | ~1 300 | Kompletterande chatbox, T0–T13 |
| `PROJEKTLEDARE_INSTRUKTION.md` | ~60 | Projektledare-roll: vad ska byggas och i vilken ordning |
| `SNICKARE_INSTRUKTION.md` | ~90 | Snickare-roll: hur man bygger, kön, BUILD_RESULT.md |
| `BUILD_RESULT.md` | — | Snickarens rapport (skapas av snickaren) |
| `KID_USER_PROMPT.md` | ~725 | Design-guide: primäranvändare är 10 år |
| `stop_app.bat` | 5 | Dödar processen på port 8001 |

---

## ✅ Fixat och verifierat i koden

| Problem | Status | Verifiering |
|---------|--------|-------------|
| P1-A — Stale `byggs` återställs vid startup | ✅ | app.py rad 32–47 |
| P1-B — Hemlighetsvakten som hårt block i `/review` | ✅ | app.py rad 3800 |
| P1-C — Hemlighetsvakten i snabbläge | ✅ FALSKT LARM | `_ALWAYS_RUN_AGENT_IDS` hanterar det, se BUG-6 |
| P1-G — `reload=False` i produktion | ✅ | app.py rad 4387 |
| P4-C — `_local_save()` dead code borttaget | ✅ | — |
| Session-namn från `tolkad_ide` | ✅ | — |
| `local_path`-inställning | ✅ | app.py settings |
| Per-projekt agentinställningar (`/api/projects/{id}/settings`) | ✅ | app.py rad 4227+ |
| `concurrency`, `krypto` (Sonnet), `agent_arkitektur` | ✅ | app.py SPECIALIST_AGENTS |
| `security`-agenten uppgraderad till Claude Sonnet 4.6 | ✅ | app.py rad ~91 |
| `projects.json` tillagd i `.gitignore` | ✅ | .gitignore rad 7 |
| **R0 — index.html avtrunkering** | ✅ | 4 121 rader, slutar `</html>` |

---

## ⚠️ Regression i `.gitignore` (unstaged — åtgärda INNAN commit)

`intrim_result*.json` togs bort ur `.gitignore` i den unstaged-ändringen.
Lägg tillbaka det innan du committar `.gitignore`:
```
intrim_result*.json
e2e_test_results*.json
```

---

## 🔴 Öppna buggar och säkerhetsproblem

### BUG/SEC-1 · Path traversal i `BUILD_RESULTS_DIR` (P1 säkerhet)

**Fil:** `app.py`, rad ~695–696

```python
ref = f"{item_id}_{attempt}.json"
(BUILD_RESULTS_DIR / ref).write_text(...)   # ← ingen sanitering av item_id
```

`item_id` kommer från URL-parametern. Ett item med `id` innehållande `../` kan skriva utanför
`build_results/`-mappen. Queue-items skapas med `uuid4()` men det är ett invariant utan enforcement.

**Fix:**
```python
ref = f"{item_id}_{attempt}.json"
target = (BUILD_RESULTS_DIR / ref).resolve()
if not str(target).startswith(str(BUILD_RESULTS_DIR.resolve())):
    return JSONResponse({"error": "Ogiltigt item_id"}, status_code=400)
(BUILD_RESULTS_DIR / ref).write_text(...)
```

### BUG-2 · `get_backlog()` läser utan lås — race condition (P1-L)

**Fil:** `app.py`, rad 3241

```python
async def get_backlog(project_id: str = ""):
    items = _backlog_load()   # ← ingen _backlog_lock
```

Alla skrivoperationer håller `_backlog_lock`. En aktiv granskning kan skriva till `backlog.json`
parallellt → delvis skriven JSON läses in → API returnerar korrupt data.

**Fix:**
```python
async def get_backlog(project_id: str = ""):
    with _backlog_lock:
        items = _backlog_load()
```

### BUG-3 · `PATCH /api/build-queue/{id}` saknar storleksgräns (P1-M)

`spec_markdown` skrivs utan längdbegränsning → 50 MB spec fryser servern vid nästa queue-operation.

**Fix:** Lägg till direkt i `patch_build_queue()`:
```python
if "spec_markdown" in payload:
    if len(str(payload["spec_markdown"])) > 100_000:
        return JSONResponse({"error": "spec_markdown överstiger 100 000 tecken."}, status_code=400)
```

### BUG-4 · `POST /api/build-queue` accepterar tom `project_id` (P1-N)

Items med `project_id=""` blöder in i alla projektvyer.

**Fix:**
```python
project_id = (payload.get("project_id") or "").strip()
if not project_id:
    return JSONResponse({"error": "project_id krävs."}, status_code=400)
```

### BUG-5 · `switchView()` raderar `builder-active`-klassen (T2 i BYGG_TASKS.md)

```javascript
// index.html rad ~1958
document.body.className = 'view-' + name;   // raderar ALLA klasser
```
Ersätt med `classList.remove(...); classList.add(...)`.

### ~~BUG-6~~ · FALSKT LARM — hemlighetsvakten hanteras korrekt i snabbläge ✅

**Verifierat 2026-06-10 mot rad 1853–1857 i app.py:**

```python
if depth == "snabb":
    always = {a["id"] for a in agents if a["id"] in _ALWAYS_RUN_AGENT_IDS}
    agents = [a for a in agents if a["id"] in _QUICK_AGENT_IDS | always]
```

`_ALWAYS_RUN_AGENT_IDS = {"hemlighetsvakten", "dataskyddsjuristen"}` läggs alltid till i
`always`-seten och uniones med `_QUICK_AGENT_IDS` — dessa agenter körs **alltid** oavsett
snabb/djup. Lägg INTE till dem i `_QUICK_AGENT_IDS`; logiken är korrekt som den är.

**BUILD_TASKS.md P1-C är stale** — tas bort från P1-prioritetslistan.

---

## Infrastrukturproblem (kvarstår från iteration 4)

### INFRA-1 · Precommit-hook saknas (TASK-10)

`app.py` och `index.html` har trunkerades upprepat av editors/agenter. En precommit-hook
fångar trasiga filer innan de committats.

**Skapa `.git/hooks/pre-commit`:**
```bash
#!/bin/bash
set -e
if git diff --cached --name-only | grep -q "app.py"; then
    python3 -c "import ast; ast.parse(open('app.py').read())" || { echo "app.py: syntax error"; exit 1; }
fi
if git diff --cached --name-only | grep -q "index.html"; then
    tail -1 index.html | grep -q "</html>" || { echo "index.html: saknar </html>"; exit 1; }
fi
```
```bash
chmod +x .git/hooks/pre-commit
```

### INFRA-2 · Branch-divergens (P1-J — beslut av Stiven)

9 lokala commits saknas på `origin/main`. `origin/main` har PR #2-mergen lokalt saknas.

```bash
# Alt A (rekommenderat): rebase lokal kod ovanpå origin/main
git rebase origin/main
# lös konflikter → git add → git rebase --continue
git push --force-with-lease
```

### INFRA-3 · `intrim_result*.json` borta från `.gitignore` (P1-I)

Regression i unstaged `.gitignore`. Lägg tillbaka raden innan commit (se ovan).

---

## DRY-brott (Spår C — R1–R7)

### DRY-1 · `_backlog_write` saknas — 9 inline atomic writes
### DRY-2 · `run_*_agent` — 5 funktioner med identisk try/parse/fallback-struktur
### DRY-3 · `async _run_*()` wrappers i `review()` — 5 identiska
### DRY-4 · Tre modellanropsvägar (multimodalt bara i run_agent-closuren)
### DRY-5 · `_github_headers()` saknas — 3 identiska headers-block i GitHub-endpoints

**Fil:** `app.py`, rader 3863–3865, 3892–3894, 3916–3919

Tre endpoints (`github_list_repos`, `github_list_branches`, `github_tree`) bygger `headers`-dict
med exakt identisk kod:
```python
headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
if token:
    headers["Authorization"] = f"Bearer {token}"
```
`github_fetch` (rad 3982–3984) gör samma sak en fjärde gång. → Extrahera `_github_headers(token)`.
Se **R7** nedan.

Fullständiga åtgärdsbeskrivningar — se R1–R7 längre ned.

---

## Arkitekturproblem (kvarstår)

| Problem | Filer | Prio |
|---------|-------|------|
| `app.py` är 4 387 rader — allt i en fil | app.py | Låg |
| `_sb_available()` saknar TTL-cache | app.py | R5 |
| `sessions.json` växer obegränsat | app.py | P1-D |
| `_RUN_RESULTS` försvinner vid omstart | app.py | P1-E |
| Ingen semaphore på `/api/review` | app.py | P1-F |
| Projektprofiler i localStorage | index.html | P3-A |
| `_sig_tokens` dedup ytlig (6-teckenprefix) | app.py | Medel |

---

## Agentnavigering

| Jag ska ändra... | Rad |
|---|---|
| Agentprompt / beteende | ~1025 (`SPECIALIST_AGENTS`) |
| Syntes-agenter (Promptsmeden etc.) | ~1855 |
| Modell-defaults | ~68 (`_DEFAULT_AGENT_MODELS`) |
| Snabb-agentlista | 1841 (`_QUICK_AGENT_IDS`) |
| Alltid-kör-agenter | 1847 (`_ALWAYS_RUN_AGENT_IDS`) |
| Backlog-affärslogik | ~347 (`backlog_add_items`) |
| `get_backlog` endpoint | 3241 |
| Byggkö PATCH | ~460 (`patch_build_queue`) |
| BUILD_RESULTS_DIR path traversal | ~695 |
| Huvud-review-flödet | ~2863 (`review()`) |
| Hemlighetsvakten-block i `/build-queue/{id}/review` | 3800 |
| Startup-hook | ~31 (`startup()`) |

---

## Vad som ALDRIG ska ändras

- `_ALWAYS_RUN_AGENT_IDS` — hemlighetsvakten + dataskyddsjuristen körs alltid
- `ThreadPoolExecutor(max_workers=80)` — kalibrerat mot parallellkörningar
- `_queue_lock` / `_backlog_lock` — load+modify+save måste vara atomiska
- Atomic write (tmp+replace) — ALLA JSON-filer måste använda detta mönster
- WIP-gränsen på 1 aktivt bygge per projekt
- CORS begränsad till localhost
- `MAX_INPUT = 450_000`

---

# Spår C — Refaktoreringsuppgifter R1–R6

> R0 är klar. Börja med R1/R2/R3 parallellt efter att P1-buggarna är fixade.

---

## R1 — Extrahera `_backlog_write` (parallellt med R2, R3)

**Fil:** `app.py`, direkt efter `_backlog_load()` (~rad 321).

```python
def _backlog_write(items: list) -> None:
    """Atomic write — caller must hold _backlog_lock."""
    tmp = BACKLOG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(BACKLOG_FILE)
```

Sök `BACKLOG_FILE.with_suffix(".tmp")` — varje träff ersätts med `_backlog_write(...)`.
Kontrollera att anropet alltid är innanför `with _backlog_lock:`.

**Acceptance criteria:**
- [ ] `_backlog_write` definierad
- [ ] Noll träffar på `BACKLOG_FILE.with_suffix(".tmp")` utanför `_backlog_write`
- [ ] `e2e_test.py` passerar

---

## R2 — Extrahera `_async_wrap` (parallellt med R1, R3)

**Fil:** `app.py`, före `review()`.

```python
async def _async_wrap(fn, *args, timeout_s: float, fallback, label: str = ""):
    try:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(executor, fn, *args),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("[%s] timeout efter %.0fs", label or getattr(fn, "__name__", "?"), timeout_s)
        return fallback
```

I `review()` — ersätt de fem `async def _run_*()` closurerna med `_async_wrap`.
OBS: `_run_krav` i granska/bugg-läge körs parallellt via `ensure_future` — behåll det.

**Acceptance criteria:**
- [ ] `_async_wrap` definierad
- [ ] Inga `async def _run_*():` lokalt inuti `review()`
- [ ] `e2e_test.py` passerar

---

## R3 — Extrahera `_run_synthesis_agent` (parallellt med R1, R2)

**Fil:** `app.py`, efter `_call_model` (~rad 2487).

```python
def _run_synthesis_agent(
    agent_def: dict, input_text: str, max_tokens: int,
    client, defaults: dict, usage_out: list = None, timeout_s: float = None,
) -> dict:
    try:
        model = get_agent_model(agent_def["id"], agent_def["model"])
        raw = _call_model(model, agent_def["system"],
                          _clamp_for_model(model, input_text),
                          max_tokens, client, usage_out=usage_out, timeout_s=timeout_s)
        text = raw.strip()
        md = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if md: text = md.group(1)
        first = _extract_first_json(text)
        if first:
            obj = json.loads(first)
            for k, v in defaults.items(): obj.setdefault(k, v)
            return obj
    except Exception as e:
        logger.error("[%s] failed: %s", agent_def["id"], e)
    return dict(defaults)
```

De 5 `run_*_agent`-funktionerna blir tunna wrappers.

**Acceptance criteria:**
- [ ] `_run_synthesis_agent` definierad
- [ ] Alla 5 `run_*_agent` delegerar till den
- [ ] `e2e_test.py` passerar

---

## R4 — Flytta bildlogik till `_call_model` (kräver R1–R3)

Multimodal bildlogik är en intern closure i `run_agent` — finns inte i `_call_model`.

1. Lägg till `images: list = None` i `_call_model`-signaturen
2. Extrahera `_build_or_content(text, images)` och `_build_anthropic_content(text, images)`
3. Ta bort den interna `_call()`-closuren i `run_agent`

**Acceptance criteria:**
- [ ] `_call_model` tar `images`-parameter
- [ ] Ingen inline bildlogik i `run_agent`
- [ ] e2e-testsektion 2 (skärmdump) passerar

---

## R5 — Cachelägg `_sb_available()` (kräver R1–R3)

```python
_sb_cache: dict = {"ok": None, "ts": 0.0}
_SB_CACHE_TTL = 60.0

def _sb_available() -> bool:
    import time as _time
    now = _time.monotonic()
    if _sb_cache["ok"] is not None and now - _sb_cache["ts"] < _SB_CACHE_TTL:
        return _sb_cache["ok"]
    result = _sb_check()   # extrahera nuvarande HTTP-logik
    _sb_cache.update(ok=result, ts=now)
    return result
```

**Acceptance criteria:**
- [ ] Max ett HTTP-anrop per 60 s mot Supabase

---

## R7 — Extrahera `_github_headers` (oberoende, låg prio)

**Fil:** `app.py`, före `github_list_repos` (~rad 3859).

```python
def _github_headers(token: str = "") -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h
```

Ersätt headers-blocket i `github_list_repos` (3863), `github_list_branches` (3892),
`github_tree` (3916) och `github_fetch` (3982) med:
```python
token = load_settings().get("github_token", "").strip()
headers = _github_headers(token)
```

**Acceptance criteria:**
- [ ] `_github_headers` definierad
- [ ] Noll inline `{"Accept": "application/vnd.github+json"...}`-block utanför `_github_headers`
- [ ] Alla fyra GitHub-endpoints returnerar samma svar som före

---

## R6 — Läs git-identitet från settings (oberoende, låg prio)

**Fil:** `push_to_github.py` (eller `.bat`), rad ~88. Ersätt hårdkodade namn:
```python
s = json.loads(SETTINGS.read_text(encoding="utf-8"))
git_email = s.get("git_email", "stiven@2snickare.se")
git_name  = s.get("git_name",  "Stiven Ishoo")
```

---

## Samlad byggordning (alla spår + prioritet)

```
━━━ OMGÅENDE (kör manuellt — inte byggartasks) ━━━
  Fixa .gitignore-regression   → lägg tillbaka intrim_result*.json
  Committa unstaged md-filer   → AGENT_CHATBOX_BUILD.md, BUILD_TASKS.md m.fl.
  Installera precommit-hook    → INFRA-1 (TASK-10 i AGENT_CHATBOX_BUILD.md)

━━━ P1 — KRITISKA BUGGAR (skicka som tasks via Projektledaren) ━━━
  BUG/SEC-1   Path traversal BUILD_RESULTS_DIR  (AW i AGENT_CHATBOX_BUILD) ← #1 säkerhet
  BUG-2       get_backlog() utan lås            (P1-L i BUILD_TASKS)
  BUG-3       spec_markdown ingen storleksgräns  (P1-M i BUILD_TASKS)
  BUG-4       tom project_id accepteras          (P1-N i BUILD_TASKS)
  ~~BUG-6~~   FALSKT LARM — hemlighetsvakten redan hanterad
  P1-D        Sessions-paginering
  P1-E        _RUN_RESULTS till disk
  P1-F        Semaphore på /api/review
  P1-H        Supabase-backup backlog+queue
  P1-J        Lös branch-divergens (beslut Stiven: Alt A eller Alt B)
  P1-K        Dubbel-anropsskydd på /review

━━━ PARALLELLT med P1 ━━━
  BUG-5       switchView() (T2 i BYGG_TASKS / AGENT_CHATBOX_BUILD)
  T4a         "builder" i _DEFAULT_AGENT_MODELS
  T4b         project_context_snapshot vid /send
  R1          _backlog_write helper
  R2          _async_wrap helper
  R3          _run_synthesis_agent helper

━━━ NÄSTA (efter P1 klart) ━━━
  Chatbox     SSE-endpoint + agent-loop (AGENT_CHATBOX_BUILD T4–T9)
  P2-D        GitHub push-endpoint
  R4          Bildlogik till _call_model
  R5          Cachelägg _sb_available

━━━ UX & FEATURES ━━━
  T13         Per-projekt agent-config UI (backend klart, frontend saknas)
  P3-A        Projektprofiler på servern
  P3-G        CI-gate med GitHub Actions
  P3-H        Historikpanel med sökning
  P3-M        Återinför _repair_truncated_json
  P3-N        Återinför vag-input-gate
  P3-Q        GitHub-filhämtning i batchar
  P3-R        Återinför kontrolleraBuild()

━━━ TEKNISK SKULD (låg prio) ━━━
  R6          git-identitet från settings
  R7          _github_headers helper (4 duplicerade headers-block)
  P4-A        __import__("httpx") → httpx (rad 3991, 4030 i github_fetch)
  P4-B        load_settings() under lock
  P4-D        Hälsokontroll med cached klient (inline openai.OpenAI() rad 4150)
  P4-E        Normalisera modellsträngar
  P4-F        GitHub inbound webhook
```

---

## Testbarhet

- `e2e_test.py` kräver levande server — ingen CI-gate ännu (P3-G)
- `ai_eval.py` kostar ~$0.30–2.00/körning — kör sparsamt
- Precommit-hook saknas (INFRA-1) — lätt att åtgärda, gör det nu

---

*Iteration 1: initial audit. 2: ny push +3 agenter. 3: BYGG_TASKS + T2-bug. 4: AGENT_CHATBOX_BUILD + BUILD_TASKS + ARKITEKTUR_ANALYS, P1-A/G/4C fixade unstaged. 5: commit bfa1f45, index.html fixad, nya P1-L/M/N + AW (path traversal) + precommit-hook, roller projektledare+snickare. 6: full läsning app.py 1–4386 klar — DRY-5 (github_headers) tillagd, R7 ny task, P4-A/P4-D radnummer bekräftade, BUG-6 klassad som falskt larm, hemlighetsvakten-logiken verifierad korrekt.*
