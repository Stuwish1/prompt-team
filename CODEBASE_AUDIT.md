# Codebase Audit — Prompt Team
> **Iteration 3** — 2026-06-10. Läs denna fil INNAN du rör kod.
> Senaste git-kontroll: ingen ny push på origin sedan iteration 2.
>
> Det finns **TWÅ parallella spår** i detta projekt:
> - **Spår A — Chatbox-feature** → se `BYGG_TASKS.md` (T1–T12, 12 uppgifter)
> - **Spår B — Refaktorering/DRY** → detta dokument (R0–R6, 7 uppgifter)
>
> T1 i BYGG_TASKS.md och R0 här är **samma uppgift** — fixa index.html.
> Gör den **en gång**, stryka den i båda filerna.

---

## Git-status

| Branch | Status |
|---|---|
| `feat/agent-audit-export` (lokal) | 8 commits före `origin/main` — ej pushad |
| `origin/main` | Har merge-commit `3654bd7` som saknas lokalt |
| Unstaged | `app.py` (+278 rader), `index.html` (+4/-44 rader), `.gitignore` |

Unstaged-ändringarna i `app.py` lägger till: 3 nya agenter (concurrency, krypto,
agent_arkitektur), per-projekt-inställningar (`_projects_write`, nya endpoints).
Dessa har **inte committats** ännu.

---

## Filkarta

| Fil | Rader | Roll |
|---|---|---|
| `app.py` | **4 337** | Hela backenden (committade rader; unstaged +278) |
| `index.html` | **4 076** | Hela frontenden — **trasig, se R0** |
| `BYGG_TASKS.md` | 1 083 | Chatbox-byggplan T1–T12 (otrackad) |
| `ai_eval.py` | ~140 | Eval-harness |
| `e2e_test.py` | ~220 | E2E-testsvit |
| `push_to_github.py` | ~100 | GitHub-push-skript |
| `backlog.json` | — | Flat-fil-databas: fynd |
| `build_queue.json` | — | Flat-fil-databas: byggkö |
| `sessions.json` | — | Flat-fil-databas: historik / Supabase |
| `settings.json` | — | API-nycklar, modeller, sökvägar |

---

## Agentkatalog (31 specialistagenter efter unstaged merge)

| ID | Modell | Ny? |
|---|---|---|
| `security` | **claude-sonnet-4.6** ↑ | Uppgraderad |
| `krypto` | **claude-sonnet-4.6** | Ny |
| `concurrency` | gemini-2.5-flash | Ny |
| `agent_arkitektur` | gemini-2.5-flash | Ny |
| Övriga 27 | gemini-2.5-flash / sonnet | Oförändrade |

`"builder"` **saknas** i `_DEFAULT_AGENT_MODELS` — behövs för T4a i BYGG_TASKS.md.

---

## 🐛 Buggar (åtgärda innan allt annat)

### BUG-1 · index.html avtrunkerad — appen är trasig (→ R0 / T1)

`index.html` slutar på rad 4076 med `updateActiveProjBadge(` utan stängning.
`</script>`, `</body>` och `</html>` saknas. Webbläsaren kastar `SyntaxError`.

### BUG-2 · `switchView()` raderar `builder-active`-klassen (→ T2 i BYGG_TASKS.md)

```javascript
// index.html rad 1958
document.body.className = 'view-' + name;  // ← raderar ALLA klasser inkl. builder-active
```

Ersätt med `classList.remove/add` så att `builder-active` överlever sidnavigering.

---

## DRY-brott

### DRY-1 · `_backlog_write` saknas — 9 inlinefall

`_queue_write` (rad 405) och `_projects_write` (rad 2064) är extraherade helpers.
Backlog saknar motsvarighet — samma tre rader är inline på 9 ställen.

**Berörda rader:** 390, 3221, 3237, 3253, 3334, 3464, 3565, 3663 (+ en via `backlog_add_items`).

### DRY-2 · `run_*_agent` — 5 funktioner med identisk struktur

`run_planner_agent` (1967), `run_krav_agent` (2535), `run_completeness_agent` (2566),
`run_backlog_agent` (2681), `run_bestallare_agent` (2732) — alla FALLBACK → get_agent_model
→ _call_model → _extract_first_json → setdefaults → return.

### DRY-3 · `async _run_*()` wrappers i `review()` — 5 identiska

Rad ~2972–3100. Alla är `try: await asyncio.wait_for(loop.run_in_executor(...), N) except asyncio.TimeoutError`.

### DRY-4 · Tre parallella modellanropsvägar

`_or_chat` direkt → `_call_model` (wrapper) → intern `_call()` closure i `run_agent`.
Multimodal bildlogik finns bara i closuren, inte i `_call_model`.

---

## Arkitekturproblem

### ARCH-1 · `app.py` = 4 337 rader — allt i en fil

Se rekommenderat paketlayout i föregående iteration (agents/, storage/, api/).

### ARCH-2 · `_sb_available()` saknar TTL-cache

Gör HTTP-anrop mot Supabase vid varje sessions-operation.

### ARCH-3 · `push_to_github.py` hardkodar e-post

Rad 88–89: `stiven@2snickare.se` / `Stiven Ishoo` — bör läsas från settings.

### ARCH-4 · `client`-parametern propageras i onödan

Nästan all trafik via OpenRouter. `get_client()` är global factory — parametern behövs inte.

---

## Agentnavigering

| Jag ska ändra... | Rad |
|---|---|
| Agentprompt / agentbeteende | 1025 (SPECIALIST_AGENTS) / ~1855 (syntes-agenter) |
| Modell-API-lager | 219 (`_or_chat`) / 2487 (`_call_model`) |
| Backlog-affärslogik | 347 (`backlog_add_items`) |
| Backlog-CRUD | 3203 |
| Byggkö-logik | 430 (`queue_create_item`) / 544 (`send_build_queue_item`) |
| Auto-granskning efter bygge | 3689 (`build_queue_review`) |
| Huvud-review-flödet | 2863 (`review`) |
| Inställningar | 122 (`load_settings`) |
| Per-projekt-inställningar | 2066 (`get_project_settings`) |
| GitHub-integration | 3811 |
| Agentmodell-defaults | 68 (`_DEFAULT_AGENT_MODELS`) |

---

## Vad som ALDRIG ska ändras

- `_ALWAYS_RUN_AGENT_IDS` — hemlighetsvakten + dataskyddsjuristen kan inte inaktiveras
- `_TRANSIENT_MARKERS` utan "timeout" — medvetet för att undvika dyr re-fakturering
- `ThreadPoolExecutor(max_workers=80)` — kalibrerat mot parallella körningar
- `_queue_lock` / `_backlog_lock` — load+modify+save måste vara atomiska
- Atomic write (tmp+replace) — alla JSON-filer MÅSTE skrivas via detta mönster
- WIP-gränsen på 1 aktivt bygge
- CORS begränsad till localhost
- `MAX_INPUT = 450_000`

---

# Spår B — Refaktoreringsuppgifter (R0–R6)

> Skicka EN i taget till byggaren. R0 → R1/R2/R3 parallellt → R4/R5 → R6.
> **R0 = T1 i BYGG_TASKS.md** — gör den en gång, stryka i båda filerna.

---

## R0 — Laga index.html (AKUT — gör FÖRST)

**Fil:** `index.html`, rad 4076 (slutet av filen).

**Filen slutar felaktigt med:**
```
    updateActiveProjBadge(
```

**Ersätt den raden med:**
```javascript
    updateActiveProjBadge();
    loadHistory();
    updateGithubSection();
    refreshByggaBadge();
  });
  setTimeout(() => runHealthCheck(), 800);
});

document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    if (!document.getElementById('runBtn').disabled) runReview();
  }
});

document.addEventListener('paste', (e) => {
  if (currentMode === 'ny_funktion') return;
  const items = (e.clipboardData || {}).items || [];
  for (const it of items) {
    if (it.type && it.type.startsWith('image/')) {
      const file = it.getAsFile();
      if (file) { _addScreenshot(file); showToast('📸 Skärmdump tillagd'); }
    }
  }
});

// ── LIVE RELOAD (dev) ──
(async () => {
  let lastMtime = null;
  const poll = async () => {
    try {
      const r = await fetch('/api/version');
      const { mtime } = await r.json();
      if (lastMtime === null) { lastMtime = mtime; return; }
      if (mtime !== lastMtime) { location.reload(); }
    } catch {}
  };
  await poll();
  setInterval(poll, 1000);
})();
</script>
</body>
</html>
```

**Acceptance criteria:**
- [ ] Filen slutar med `</html>`
- [ ] Inga JS-syntaxfel i webbläsarkonsolen vid sidladdning
- [ ] http://localhost:8001 laddar utan vit skärm
- [ ] Ctrl+Enter triggar granskning
- [ ] Klistra in bild i granska-läge fungerar

---

## R1 — Extrahera `_backlog_write` (kan köras parallellt med R2, R3)

**Fil:** `app.py`

**Lägg till direkt efter `_backlog_load()` (~rad 321):**
```python
def _backlog_write(items: list) -> None:
    """Atomic write — caller must hold _backlog_lock."""
    tmp = BACKLOG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(BACKLOG_FILE)
```

**Ersätt alla 9 inline-skrivningar** — varje ser ut som:
```python
tmp = BACKLOG_FILE.with_suffix(".tmp")
tmp.write_text(json.dumps(...), encoding="utf-8")
tmp.replace(BACKLOG_FILE)
```
Sök efter `BACKLOG_FILE.with_suffix(".tmp")` — varje träff ska ersättas med `_backlog_write(...)`.

**Berörda ställen:** rad 390, 3221, 3237, 3253, 3464, 3565, 3663. Kontrollera att anropet
alltid sker innanför rätt `with _backlog_lock:`-block.

**Acceptance criteria:**
- [ ] `_backlog_write` finns och ser identisk ut med `_queue_write`
- [ ] Inga `BACKLOG_FILE.with_suffix(".tmp")` kvar utanför `_backlog_write`
- [ ] `e2e_test.py` passerar mot levande server

---

## R2 — Extrahera `_async_wrap` (kan köras parallellt med R1, R3)

**Fil:** `app.py` — lägg till i "CORE LOGIC"-sektionen, före `review()`

```python
async def _async_wrap(fn, *args, timeout_s: float, fallback, label: str = ""):
    """Run a sync fn in the executor with timeout. Returns fallback on TimeoutError."""
    try:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(executor, fn, *args),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("[%s] timeout efter %.0fs", label or getattr(fn, "__name__", "?"), timeout_s)
        return fallback
```

**I `review()` (~rad 2863), ersätt de fem interna wrapparna:**

| Nuvarande wrapper | Ersätt med |
|---|---|
| `async def _run_krav()` | `_async_wrap(run_krav_agent, ..., timeout_s=120.0, fallback={...}, label="kravanalytikern")` |
| `async def _run_backlog()` | `_async_wrap(run_backlog_agent, ..., timeout_s=120.0, fallback={"items":[],"note":""}, label="backloghallaren")` |
| `async def _run_smith()` | `_async_wrap(run_prompt_smith, ..., timeout_s=240.0, fallback={"type":"error",...}, label="prompt_smith")` |
| `async def _run_completeness()` | `_async_wrap(run_completeness_agent, ..., timeout_s=120.0, fallback={}, label="kompletthetsgranskaren")` |
| `async def _run_bestallare()` | `_async_wrap(run_bestallare_agent, ..., timeout_s=120.0, fallback={}, label="bestallarsammanfattaren")` |

**OBS:** `_run_krav` i review/bugg-läge körs som `asyncio.ensure_future(...)` för
att köra parallellt med specialisterna. Behåll den parallelliteten — schemalägg
med `asyncio.ensure_future(_async_wrap(...))` och invänta resultatet efteråt.

**Acceptance criteria:**
- [ ] `_async_wrap` definierad och dokumenterad
- [ ] Inga `async def _run_*():` lokalt inuti `review()`
- [ ] Parallell krav-körning i granska/bugg-läge fungerar
- [ ] `e2e_test.py` passerar

---

## R3 — Extrahera `_run_synthesis_agent` (kan köras parallellt med R1, R2)

**Fil:** `app.py` — lägg till efter `_call_model` (~rad 2487)

```python
def _run_synthesis_agent(
    agent_def: dict,
    input_text: str,
    max_tokens: int,
    client,
    defaults: dict,
    usage_out: list = None,
    timeout_s: float = None,
) -> dict:
    """Generic synthesis agent runner — FALLBACK=defaults on any error."""
    try:
        model = get_agent_model(agent_def["id"], agent_def["model"])
        raw = _call_model(
            model, agent_def["system"],
            _clamp_for_model(model, input_text),
            max_tokens, client,
            usage_out=usage_out, timeout_s=timeout_s,
        )
        text = raw.strip()
        md = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if md:
            text = md.group(1)
        first = _extract_first_json(text)
        if first:
            obj = json.loads(first)
            for k, v in defaults.items():
                obj.setdefault(k, v)
            return obj
    except Exception as e:
        logger.error("[%s] failed: %s", agent_def["id"], e)
    return dict(defaults)
```

**Skriv om de fem `run_*_agent`-funktionerna** som tunna wrappers. Exempel för
`run_completeness_agent`:
```python
def run_completeness_agent(spec_content, model, client, usage_out=None, profile=None):
    extra = "\n\n" + byggsatt_smith_directives(profile) if profile else ""
    agent = {**COMPLETENESS_AGENT, "system": COMPLETENESS_AGENT["system"] + extra}
    return _run_synthesis_agent(
        agent, spec_content, 2000, client,
        defaults={"status": "OKÄND", "completeness_score": 0, "saknas": [], "styrkor": []},
        usage_out=usage_out,
    )
```

`run_backlog_agent` och `run_bestallare_agent` bygger en sammansatt input-sträng
(fynd + kontextblock) **innan** anropet — håll den logiken i wrappers, kalla sedan
`_run_synthesis_agent` med den färdiga strängen.

**Acceptance criteria:**
- [ ] `_run_synthesis_agent` definierad
- [ ] Alla 5 `run_*_agent`-funktioner delegerar till den
- [ ] Ingen FALLBACK-dict dupliceras
- [ ] `e2e_test.py` passerar

---

## R4 — Flytta bildlogik till `_call_model` (kräver R1–R3 klara)

**Fil:** `app.py`

Multimodalt innehållsbygge är en intern `_call()`-closure i `run_agent` (~rad 2358).
Det finns inte i `_call_model`. Konsekvens: tre separata anropsvägar till modell-API.

**Steg:**
1. Lägg till `images: list = None` i `_call_model`-signaturen (rad 2487)
2. Extrahera `_build_or_content(text, images)` och `_build_anthropic_content(text, images)`
3. Flytta bildlogiken dit från `run_agent`'s `_call()`-closure
4. Ta bort den interna `_call()`-closuren — `run_agent` kallar `_call_model` direkt

**Acceptance criteria:**
- [ ] `_call_model` tar `images`-parameter
- [ ] Ingen inline bildskapning kvar i `run_agent`
- [ ] e2e-test sektion [2] (buggrapport + skärmdump) passerar

---

## R5 — Cachelägg `_sb_available()` (kräver R1–R3 klara)

**Fil:** `app.py`, rad ~851

```python
_sb_cache: dict = {"ok": None, "ts": 0.0}
_SB_CACHE_TTL = 60.0

def _sb_available() -> bool:
    import time as _time
    now = _time.monotonic()
    if _sb_cache["ok"] is not None and now - _sb_cache["ts"] < _SB_CACHE_TTL:
        return _sb_cache["ok"]
    result = _sb_check()   # extrahera nuvarande HTTP-logik till _sb_check()
    _sb_cache.update(ok=result, ts=now)
    return result
```

**Acceptance criteria:**
- [ ] Max ett HTTP-anrop per 60 sekunder mot Supabase
- [ ] Sessions sparas fortfarande korrekt om Supabase konfigurerat

---

## R6 — Läs git-identitet från settings (oberoende, låg prio)

**Fil:** `push_to_github.py`, rad 88–89

```python
# Ersätt hårdkodade värden med:
s = json.loads(SETTINGS.read_text(encoding="utf-8"))
git_email = s.get("git_email", "stiven@2snickare.se")
git_name  = s.get("git_name",  "Stiven Ishoo")
git(f'config user.email "{git_email}"')
git(f'config user.name  "{git_name}"')
```

Lägg till `"git_email": ""` och `"git_name": ""` i `load_settings()` defaults (~rad 122).

**Acceptance criteria:**
- [ ] Inga hardkodade namn/e-post i `push_to_github.py`
- [ ] Fallback-värden finns om fälten saknas i settings

---

## Samlad byggordning

```
IDAG (AKUT):
  R0 = T1  →  Laga index.html (appen är trasig)

PARALLELLT (när R0 är klar):
  R1        →  Extrahera _backlog_write
  R2        →  Extrahera _async_wrap
  R3        →  Extrahera _run_synthesis_agent
  T2        →  Fixa switchView() (se BYGG_TASKS.md)
  T3        →  Komplettera .gitignore (se BYGG_TASKS.md)
  T4a       →  Lägg till "builder" i _DEFAULT_AGENT_MODELS (se BYGG_TASKS.md)
  T4b / T10 →  project_context_snapshot vid /send (se BYGG_TASKS.md)

NÄSTA STEG (när parallellspåret är klart):
  R4        →  Flytta bildlogik till _call_model
  R5        →  Cachelägg _sb_available()
  T4        →  SSE-endpoint + BUILDER_TOOLS (se BYGG_TASKS.md — 4-6h)

SEDAN (beror på T4):
  T5 → T6 → T7 → T8 → T9  (Frontend chatbox-UI)

SIST (oberoende):
  R6        →  git-identitet från settings
  T11       →  AGENT_DISPLAY_NAMES
  T12       →  Reconnect-knapp
```

---

## Testbarhet

- `e2e_test.py` kräver levande server. Ingen unit-testsvit.
- `ai_eval.py` kostar $0.30–2.00/körning — kör sparsamt.
- **Saknas unit-tester** för: `backlog_add_items` (dedup), `_parse_agent_json`,
  `_repair_truncated_json`, `_is_same_issue`. Kan testas utan modell-API.

---

*Stryka en uppgift när den är klar. Uppdatera radnummer om de glidit.*
*Föregående iterationer: Iteration 1 (initial audit), Iteration 2 (ny push med 3 agenter + per-projekt-inställningar).*
