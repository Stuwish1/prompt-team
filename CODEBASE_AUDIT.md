# Codebase Audit — Prompt Team
> **Iteration 7** — 2026-06-10. Läs denna fil INNAN du rör kod.
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
| `app.py` | **4 683** | Hela backenden — syntax OK (verifierat t.o.m. rad 4683) |
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
| Per-projekt agentinställningar (`/api/projects/{id}/settings`) | ✅ | app.py rad 4661–4683 |
| `concurrency`, `krypto` (Sonnet), `agent_arkitektur` | ✅ | app.py SPECIALIST_AGENTS |
| `security`-agenten uppgraderad till Claude Sonnet 4.6 | ✅ | app.py rad ~91 |
| `projects.json` tillagd i `.gitignore` | ✅ | .gitignore rad 7 |
| **R0 — index.html avtrunkering** | ✅ | 4 121 rader, slutar `</html>` |
| **BUG/SEC-1 — path traversal** | ✅ BEKRÄFTAT FIXAD | app.py rad 902–906 + rad 4087–4089 |
| **P1-L — get_backlog() lås** | ✅ | per PROJECT_STATUS |
| **P1-M — spec_markdown storleksgräns** | ✅ | per PROJECT_STATUS |
| **P1-N — tom project_id** | ✅ | per PROJECT_STATUS |
| **P1-P — TOCTOU i build_queue_review** | ✅ BEKRÄFTAT FIXAD | app.py rad 4058–4070 |
| **P1-Q — backlog_to_spec/verify lås** | ✅ BEKRÄFTAT FIXAD | app.py rad 3855 + 3976 |
| **P3-T — _progress_set GC** | ✅ | per PROJECT_STATUS |
| **13d/P4-i — health_check inline klient** | ✅ BEKRÄFTAT FIXAD | rad 4537: `get_openrouter_client()` |
| **GitHub webhook (9n/P4-b)** | ✅ IMPLEMENTERAD | app.py rad 4447–4482 |

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

### ~~BUG/SEC-1~~ · Path traversal — ✅ BEKRÄFTAT FIXAD (iteration 7)

**Verifierat i koden:**
- `build_queue_result()` — rad 902–906: `.resolve()` + parent-check
- `build_queue_review()` — rad 4087–4089: samma skydd

```python
result_path = (BUILD_RESULTS_DIR / item["result_ref"]).resolve()
if BUILD_RESULTS_DIR.resolve() not in result_path.parents:
    return JSONResponse({"error": "Ogiltigt sökväg för byggresultat."}, status_code=400)
```

Queue-item i kön är stale — kan stängas.

### ~~BUG-2~~ · `get_backlog()` lås — ✅ FIXAD (P1-L per PROJECT_STATUS)

### ~~BUG-3~~ · `spec_markdown` storleksgräns — ✅ FIXAD (P1-M per PROJECT_STATUS)

### ~~BUG-4~~ · Tom `project_id` — ✅ FIXAD (P1-N per PROJECT_STATUS)

### BUG-5 · `switchView()` raderar `builder-active`-klassen (T2 i BYGG_TASKS.md)

```javascript
// index.html rad ~1958
document.body.className = 'view-' + name;   // raderar ALLA klasser
```
Ersätt med `classList.remove(...); classList.add(...)`.

### BUG-6 · Uppskjutna imports inuti funktioner (P4 kvalitet)

**Fil:** `app.py`

Tre imports sker inuti funktioner istället för på modulnivå:

| Import | Plats | Problem |
|---|---|---|
| `import base64` | rad 4367, inuti `fetch_file()` som är en closure inuti `github_fetch()` | Re-importeras vid varje filhämtning |
| `import socket` | rad 4586, inuti `health_check()` | Re-importeras vid varje hälsokontroll |
| `from urllib.parse import urlparse` | rad 4594, inuti `health_check()` | Same |

`base64` och `socket` är standardbibliotek — flytta till toppen av filen.

**Fix:** Lägg till i importblocket (rad ~1–30):
```python
import base64
import socket
from urllib.parse import urlparse
```
Ta sedan bort de lokala import-satserna.

### BUG-7 · UTRED: app.py rad 4676 — rapporterat SyntaxError

LOGG_FYND.md rapporterar att `app.py` är trunkerad vid rad 4676 med SyntaxError. **Iteration 7-läsning visar att detta sannolikt är ett falskt larm:** filen läses komplett t.o.m. rad 4683 och `get_project_settings_api`-funktionen är syntaktiskt korrekt. Rad 4676 innehåller:
```python
    "modes": a.get("modes", []),
```
— giltig Python inuti en list comprehension. Filen slutar korrekt med `}` på rad 4682.

**Åtgärd:** Kör `python3 -c "import ast; ast.parse(open('app.py').read()); print('OK')"` för att bekräfta. Om OK — stäng queue-itemet.

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
| Agentprompt / beteende | ~1270 (`SPECIALIST_AGENTS`) |
| Syntes-agenter (Promptsmeden etc.) | ~2083 |
| Modell-defaults | ~258 (`_DEFAULT_AGENT_MODELS`) |
| Snabb-agentlista | 2083 (`_QUICK_AGENT_IDS`) |
| Alltid-kör-agenter | 2089 (`_ALWAYS_RUN_AGENT_IDS`) |
| Backlog-affärslogik | ~519 (`backlog_add_items`) |
| `get_backlog` endpoint | ~3563 |
| Byggkö PATCH | ~611 (`queue_create_item`) |
| BUILD_RESULTS_DIR path traversal (FIXAD) | 902–906, 4087–4089 |
| Huvud-review-flödet | ~3159 (`review()`) |
| Hemlighetsvakten-block i `/build-queue/{id}/review` | ~4132 |
| Startup-hook | ~35 (`startup()`) |
| GitHub webhook | 4447–4482 |
| Per-projekt agentinställningar | 4661–4683 |
| `_to_spec_phased` (fas-uppdelning) | ~3720 |
| `backlog_to_spec` | 3851 |
| `backlog_verify_fix` | 3972 |
| `build_queue_review` | 4052 |
| GitHub fetch | 4278 |
| Hälsokontroll | 4522 |

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

Multimodal bildlogik är en intern closure i `run_agent` — finns inte i `_ca