# BYGG_TASKS.md — Prompt Team Builder Chatbox
> Senast uppdaterad: 2026-06-10  
> Källa: AGENT_CHATBOX_BUILD.md (Iteration 10, BYGGPLAN v3) + verifierad app.py (4386 rader) + index.html (4121 rader)

---

## STATUSÖVERSIKT

| ID | Uppgift | Status |
|----|---------|--------|
| T0 | Git: rebase/merge mot origin/main | ❌ |
| T1 | index.html fix (trunkering) | ✅ KLAR |
| T2 | switchView() builder-active fix | ❌ |
| T3 | .gitignore uppdatering | ❌ |
| T4 | Builder SSE endpoint `/api/builder/stream/{id}` | ❌ |
| T4b | `project_context_snapshot` i `send_build_queue_item()` | ❌ |
| T5 | `#builderPanel` HTML + CSS | ❌ |
| T6 | `openBuilderPanel()` JS | ❌ |
| T7 | `startBuild()` → `openBuilderPanel()` | ❌ |
| T8 | `renderQueueBox()` byggknapp | ❌ |
| T9 | `local_path` UI-fält i settings modal | ❌ |
| T10 | Pre-commit hook filintegritet | ❌ |
| T11 | `AGENT_DISPLAY_NAMES` komplett (37 agenter) | ❌ |
| T12 | `_memory_gc_loop` för _progress/_RUN_RESULTS | ❌ |
| T13 | Path traversal guard i `build_queue_result()` | ❌ |
| T14 | `request_disabled` whitelist i `/api/review` | ❌ |
| T15 | Byte-gräns för bilder i `review()` | ❌ |
| T16 | `model`-fält längdvalidering i `post_settings()` | ❌ |
| T17 | `_SEVERITY_GUIDE` lägg till `motivering`-fält | ❌ |
| T18 | Per-projekt agent-config UI (frontend) | ❌ |

---

## KÄNDA FALLGROPAR

**F1** — `build_queue_review()` returnerar `review_session_id` på TOP-NIVÅ (inte inuti `verdict`).  
Rätt: `review_result.get("review_session_id", "")` — INTE `review_result["verdict"].get("run_id")`

**F2** — `github_fetch()` returnerar `JSONResponse` vid fel (inte dict).  
Lägg till guard: `if isinstance(code_resp, JSONResponse): return code_resp`

**F3** — `_DEFAULT_AGENT_MODELS` använder OpenRouter-format `"anthropic/claude-sonnet-4.6"`.  
Normalisera för Anthropic SDK: `.removeprefix("anthropic/").replace(".", "-")` → `"claude-sonnet-4-6"`

**F4** — `_SEVERITY_GUIDE` schema saknar `motivering`-fält (se T17).

**F5** — `_queue_load()` / `_queue_write()` / `_queue_lock` — ALL queue-access MÅSTE gå via dessa helpers.

**F6** — `_sse()` MÅSTE inkludera `event:`-rad, annars fungerar aldrig `EventSource.addEventListener('builder_log', ...)`.  
Rätt format:
```python
def _sse(obj: dict) -> str:
    evt = obj.get("type", "message")
    return f"event: {evt}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n"
```

**F7** — `EventSource` är ENRIKTAD. `sendBuilderMessage()` behöver ett SEPARAT POST-endpoint.

**F8** — `kontrolleraBuild()` i index.html (rad ~2140) är den BEFINTLIGA GitHub-fetch + AI-review-funktionen. Ersätt DEN INTE — lägg till `openBuilderPanel()` som en extra knapp.

---

## T0 — Git: Diverged history

**Situation:** 9 lokala commits ahead, remote har 1 merge-commit (3654bd7) lokal saknar.

```bash
git fetch origin
git rebase origin/main   # eller: git merge origin/main
# lös ev. konflikter, sedan:
git push origin main
```

---

## T1 — index.html trunkering ✅ KLAR

Bekräftat: index.html är 4121 rader, sista raden är `</html>`. Inget att göra.

---

## T2 — switchView() builder-active fix

**Fil:** `index.html`  
**Problem:** Öppnar man en annan vy (t.ex. kö) medan builder-panelen är öppen stängs den inte.

**Sök:** `function switchView(` och lägg till i loopkroppen:

```javascript
// I switchView(), i loopen som tar bort "active" från navknappar:
document.getElementById('builderPanel')?.classList.remove('active');
```

---

## T3 — .gitignore

Säkerställ att följande finns:

```
__pycache__/
*.pyc
.env
*.db
build_results/
*.log
node_modules/
.DS_Store
```

---

## T4 — Builder SSE endpoint

**Fil:** `app.py`  
**Placering:** Lägg till efter `build_queue_review()`-routen.

```python
@app.get("/api/builder/stream/{item_id}")
async def builder_stream(item_id: str, request: Request):
    """SSE-stream som kör alla byggagenter och streamar loggar."""

    def _sse(obj: dict) -> str:
        evt = obj.get("type", "message")
        return f"event: {evt}\ndata: {json.dumps(obj, ensure_ascii=False)}\n\n"

    async def generate():
        queue = await _queue_load()
        item = next((x for x in queue if x["id"] == item_id), None)
        if not item:
            yield _sse({"type": "error", "message": f"Ärende {item_id} hittades inte"})
            return

        project_id = item.get("project_id", "")
        project = next((p for p in _projects_load() if p["id"] == project_id), {})

        # Hämta aktiverade agenter för projektet (eller globalt)
        proj_settings = project.get("settings", {})
        disabled = set(proj_settings.get("disabled_agents", []))
        agents_to_run = [a for a in SPECIALIST_AGENTS if a not in disabled]

        yield _sse({"type": "builder_start", "item_id": item_id,
                    "agent_count": len(agents_to_run)})

        # Normalisera modell för Anthropic SDK (F3)
        raw_model = _settings_load().get("model", DEFAULT_MODEL)
        model = raw_model.removeprefix("anthropic/").replace(".", "-")

        client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

        results: list[dict] = []
        for agent_id in agents_to_run:
            if await request.is_disconnected():
                break
            yield _sse({"type": "builder_log", "agent": agent_id,
                        "status": "running", "message": f"Kör {agent_id}…"})
            try:
                agent_def = _SPECIALIST_AGENTS_MAP.get(agent_id, {})
                sys_prompt = agent_def.get("system", "Du är en kodgranskare.")
                user_msg = _build_agent_prompt(item, project, agent_id)

                agent_result: dict = {}
                async with client.messages.stream(
                    model=model, max_tokens=2048,
                    system=sys_prompt,
                    messages=[{"role": "user", "content": user_msg}]
                ) as stream:
                    full_text = ""
                    async for chunk in stream.text_stream:
                        full_text += chunk
                        yield _sse({"type": "builder_chunk",
                                    "agent": agent_id, "chunk": chunk})
                    agent_result = {"agent": agent_id, "output": full_text,
                                    "status": "ok"}

            except Exception as exc:
                agent_result = {"agent": agent_id, "output": str(exc),
                                "status": "error"}
                yield _sse({"type": "builder_log", "agent": agent_id,
                            "status": "error", "message": str(exc)})

            results.append(agent_result)
            yield _sse({"type": "builder_log", "agent": agent_id,
                        "status": "done",
                        "message": f"{agent_id} klart"})

        # Spara resultat
        session_id = str(uuid.uuid4())[:8]
        _save_build_result(item_id, session_id, results)

        yield _sse({"type": "builder_done", "item_id": item_id,
                    "session_id": session_id, "agent_count": len(results)})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/builder/message/{item_id}")
async def builder_message(item_id: str, payload: dict = Body(...)):
    """Ta emot meddelanden från chatboxen (F7 — EventSource är enriktad)."""
    msg = payload.get("message", "").strip()
    if not msg:
        raise HTTPException(400, "Tomt meddelande")
    # Lägg i kö / bearbeta async — implementera enligt behov
    return {"ok": True, "item_id": item_id, "received": msg}
```

---

## T4b — project_context_snapshot i send_build_queue_item()

**Fil:** `app.py`  
**Sök:** `async def send_build_queue_item(`

Lägg till snapshot INNAN API-anropet:

```python
# Snapshot av projektkontext vid byggtillfället
project_context_snapshot = {
    "repo": project.get("repo", ""),
    "local_path": project.get("local_path", ""),
    "branch": project.get("branch", "main"),
    "snapshot_ts": datetime.utcnow().isoformat(),
}
item["project_context_snapshot"] = project_context_snapshot
```

---

## T5 — #builderPanel HTML + CSS

**Fil:** `index.html`  
**Placering:** Lägg till direkt innan `</body>`.

```html
<!-- ===== BUILDER PANEL ===== -->
<div id="builderPanel" class="builder-panel" role="dialog" aria-modal="true"
     aria-labelledby="builderPanelTitle">
  <div class="builder-panel__header">
    <h2 id="builderPanelTitle" class="builder-panel__title">Byggagenten</h2>
    <div class="builder-panel__meta" id="builderPanelMeta"></div>
    <button class="builder-panel__close" onclick="closeBuilderPanel()"
            aria-label="Stäng">✕</button>
  </div>

  <div class="builder-panel__log" id="builderPanelLog" aria-live="polite">
    <p class="builder-panel__placeholder">Starta ett bygge för att se loggar här.</p>
  </div>

  <div class="builder-panel__progress" id="builderPanelProgress" style="display:none">
    <div class="builder-panel__progress-bar" id="builderPanelProgressBar"></div>
  </div>

  <div class="builder-panel__chat">
    <textarea id="builderChatInput" class="builder-panel__input"
              placeholder="Skriv till agenten…" rows="2"
              onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendBuilderMessage();}">
    </textarea>
    <button class="btn btn-primary" onclick="sendBuilderMessage()">Skicka</button>
    <button class="btn btn-ghost" id="builderReconnectBtn"
            onclick="reconnectBuilderStream()" style="display:none">
      Återanslut
    </button>
  </div>
</div>
<div id="builderPanelOverlay" class="builder-panel__overlay"
     onclick="closeBuilderPanel()"></div>
```

**CSS** (lägg i `<style>`-blocket):

```css
.builder-panel {
  position: fixed; inset: 0 0 0 auto;
  width: min(480px, 100vw);
  background: var(--bg-surface, #1e1e2e);
  border-left: 1px solid var(--border, #333);
  display: flex; flex-direction: column;
  transform: translateX(100%);
  transition: transform .25s ease;
  z-index: 900;
  font-family: var(--font-mono, monospace);
}
.builder-panel.active { transform: translateX(0); }

.builder-panel__overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.45);
  display: none; z-index: 899;
}
.builder-panel__overlay.active { display: block; }

.builder-panel__header {
  display: flex; align-items: center; gap: .5rem;
  padding: .75rem 1rem;
  border-bottom: 1px solid var(--border, #333);
  background: var(--bg-elevated, #2a2a3e);
}
.builder-panel__title { margin: 0; font-size: 1rem; flex: 1; }
.builder-panel__meta { font-size: .75rem; color: var(--text-muted, #888); }
.builder-panel__close {
  background: none; border: none; cursor: pointer;
  color: var(--text-muted, #888); font-size: 1.1rem; padding: .25rem .5rem;
}
.builder-panel__close:hover { color: var(--text, #fff); }

.builder-panel__log {
  flex: 1; overflow-y: auto; padding: .75rem 1rem;
  font-size: .8rem; line-height: 1.5;
  display: flex; flex-direction: column; gap: .25rem;
}
.builder-panel__placeholder { color: var(--text-muted, #888); }

.builder-log-entry { padding: .25rem .5rem; border-radius: 4px; }
.builder-log-entry.running { color: #7ec8e3; }
.builder-log-entry.done    { color: #a8e6a3; }
.builder-log-entry.error   { color: #f08080; }
.builder-log-entry.chunk   {
  font-size: .75rem; color: var(--text-muted, #888);
  white-space: pre-wrap; word-break: break-word;
}

.builder-panel__progress {
  height: 3px; background: var(--border, #333);
}
.builder-panel__progress-bar {
  height: 100%; background: var(--accent, #7c6af7);
  width: 0; transition: width .3s ease;
}

.builder-panel__chat {
  display: flex; gap: .5rem; padding: .75rem 1rem;
  border-top: 1px solid var(--border, #333);
  background: var(--bg-elevated, #2a2a3e);
}
.builder-panel__input {
  flex: 1; resize: none;
  background: var(--bg-input, #12121a);
  border: 1px solid var(--border, #333);
  color: var(--text, #fff);
  border-radius: 6px; padding: .4rem .6rem;
  font-family: inherit; font-size: .85rem;
}
.builder-panel__input:focus { outline: 1px solid var(--accent, #7c6af7); }
```

---

## T6 — openBuilderPanel() JS

**Fil:** `index.html`  
**Placering:** Lägg till i `<script>`-blocket (nära andra panel-funktioner).

```javascript
// ===== BUILDER PANEL =====
let _builderItemId = null;
let _builderES = null;         // EventSource
let _builderAgentCount = 0;
let _builderAgentsDone = 0;

function openBuilderPanel(itemId) {
  _builderItemId = itemId;
  _builderAgentsDone = 0;

  const panel   = document.getElementById('builderPanel');
  const overlay = document.getElementById('builderPanelOverlay');
  const log     = document.getElementById('builderPanelLog');
  const meta    = document.getElementById('builderPanelMeta');
  const prog    = document.getElementById('builderPanelProgress');
  const bar     = document.getElementById('builderPanelProgressBar');
  const reconnBtn = document.getElementById('builderReconnectBtn');

  log.innerHTML = '<p class="builder-panel__placeholder">Ansluter…</p>';
  meta.textContent = `Ärende: ${itemId}`;
  prog.style.display = 'none';
  bar.style.width = '0%';
  reconnBtn.style.display = 'none';

  panel.classList.add('active');
  overlay.classList.add('active');
  document.body.style.overflow = 'hidden';

  _startBuilderStream(itemId);
}

function _startBuilderStream(itemId) {
  if (_builderES) { _builderES.close(); _builderES = null; }

  const es = new EventSource(`/api/builder/stream/${itemId}`);
  _builderES = es;

  const log = document.getElementById('builderPanelLog');
  const bar = document.getElementById('builderPanelProgressBar');
  const prog = document.getElementById('builderPanelProgress');
  const reconnBtn = document.getElementById('builderReconnectBtn');

  function addEntry(text, cls = '') {
    const div = document.createElement('div');
    div.className = 'builder-log-entry ' + cls;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  es.addEventListener('builder_start', e => {
    const d = JSON.parse(e.data);
    _builderAgentCount = d.agent_count || 0;
    log.innerHTML = '';
    prog.style.display = 'block';
    addEntry(`Startar ${_builderAgentCount} agenter…`, 'running');
  });

  es.addEventListener('builder_log', e => {
    const d = JSON.parse(e.data);
    if (d.status === 'running') addEntry(`⟳ ${d.agent}: ${d.message}`, 'running');
    else if (d.status === 'done') {
      _builderAgentsDone++;
      const pct = _builderAgentCount
        ? Math.round((_builderAgentsDone / _builderAgentCount) * 100) : 0;
      bar.style.width = pct + '%';
      addEntry(`✓ ${d.agent}`, 'done');
    } else if (d.status === 'error') {
      addEntry(`✗ ${d.agent}: ${d.message}`, 'error');
    }
  });

  es.addEventListener('builder_chunk', e => {
    const d = JSON.parse(e.data);
    const last = log.querySelector('.builder-log-entry.chunk:last-child');
    const isCurrentAgent = last?.dataset.agent === d.agent;
    if (isCurrentAgent) {
      last.textContent += d.chunk;
    } else {
      const div = document.createElement('div');
      div.className = 'builder-log-entry chunk';
      div.dataset.agent = d.agent;
      div.textContent = d.chunk;
      log.appendChild(div);
    }
    log.scrollTop = log.scrollHeight;
  });

  es.addEventListener('builder_done', e => {
    const d = JSON.parse(e.data);
    bar.style.width = '100%';
    addEntry(`✅ Bygge klart! Session: ${d.session_id}`, 'done');
    es.close();
    _builderES = null;
  });

  es.addEventListener('error', () => {
    addEntry('⚠ Anslutning bruten.', 'error');
    reconnBtn.style.display = 'inline-block';
    es.close();
    _builderES = null;
  });
}

function closeBuilderPanel() {
  if (_builderES) { _builderES.close(); _builderES = null; }
  document.getElementById('builderPanel').classList.remove('active');
  document.getElementById('builderPanelOverlay').classList.remove('active');
  document.body.style.overflow = '';
}

function reconnectBuilderStream() {
  if (!_builderItemId) return;
  document.getElementById('builderReconnectBtn').style.display = 'none';
  _startBuilderStream(_builderItemId);
}

async function sendBuilderMessage() {
  const input = document.getElementById('builderChatInput');
  const msg = input.value.trim();
  if (!msg || !_builderItemId) return;
  input.value = '';
  try {
    await fetch(`/api/builder/message/${_builderItemId}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg})
    });
  } catch (err) {
    console.error('sendBuilderMessage:', err);
  }
}
```

---

## T7 — startBuild() ersätt med openBuilderPanel()

**Fil:** `index.html`  
**Sök:** `function startBuild(` (rad ~2111)

Nuläge använder `navigator.clipboard.writeText(...)`. Ersätt hela funktionen:

```javascript
function startBuild(itemId) {
  openBuilderPanel(itemId);
}
```

---

## T8 — renderQueueBox() byggknapp

**Fil:** `index.html`  
**Sök:** `function renderQueueBox(` — hitta blocket för `byggs`-status.

Byt ut actions-strängen för `byggs`-ärenden till:

```javascript
const hasRepo = !!(getActiveProject()?.repo);
actions = `<button class="btn btn-primary" onclick="openBuilderPanel('${it.id}')">Visa byggagenten</button>`
  + (hasRepo
      ? `<button class="btn btn-ghost" onclick="kontrolleraBuild('${it.id}', this)" style="font-size:11px;">Kontrollera mot GitHub</button>`
      : `<button class="btn btn-ghost" onclick="openBuildResult('${it.id}')" style="font-size:11px;">Klistra in kod manuellt</button>`)
  + `<button class="btn btn-ghost" onclick="queueSetStatus('${it.id}','ko')" style="font-size:11px;">Tillbaka till kö</button>`;
```

> ⚠️ **F8** — `kontrolleraBuild()` BEVARAS. Lägg bara till `openBuilderPanel`-knappen bredvid.

---

## T9 — local_path UI-fält i settings modal

**Fil:** `index.html`  
**Sök:** settings modal (`#settingsModal` eller liknande) — efter `repo`-fältet.

```html
<div class="form-group">
  <label for="localPathInput">Lokal sökväg (valfri)</label>
  <input type="text" id="localPathInput" class="form-control"
         placeholder="/Users/du/projekt/mitt-repo">
  <small class="form-hint">Absolut sökväg till repot på din dator.</small>
</div>
```

**JS** — i `openSettings()`:
```javascript
document.getElementById('localPathInput').value =
  getActiveProject()?.local_path ?? '';
```

**JS** — i `saveSettings()` payload:
```javascript
local_path: document.getElementById('localPathInput').value.trim(),
```

---

## T10 — Pre-commit hook

**Fil:** `.git/hooks/pre-commit` (kör `chmod +x` efteråt)

```bash
#!/usr/bin/env bash
set -e

# Kontrollera att index.html är komplett
last=$(tail -1 index.html | tr -d '[:space:]')
if [ "$last" != "</html>" ]; then
  echo "index.html verkar trunkerad (sista raden: '$last')"
  exit 1
fi

# Kontrollera Python-syntax
if command -v python3 &>/dev/null; then
  python3 -m py_compile app.py && echo "app.py syntax OK"
fi

echo "Pre-commit OK"
```

---

## T11 — AGENT_DISPLAY_NAMES komplett (37 agenter)

**Fil:** `index.html`  
**Sök:** `const AGENT_DISPLAY_NAMES` (rad ~1357) — ersätt hela objektet:

```javascript
const AGENT_DISPLAY_NAMES = {
  kravanalytikern:    '📋 Kravanalytikern',
  architecture:       '🏗️ Arkitekten',
  ux:                 '🎨 UX-agenten',
  database:           '🗄️ Databasagenten',
  risk:               '⚠️ Riskvärderaren',
  integration:        '🔗 Integrationsanalytikern',
  prompt_smith:       '✍️ Promptsmeden',
  completeness:       '✅ Kompletthetsgranskaren',
  hotmodelleraren:    '🎯 Hotmodelleraren',
  dataskyddsjuristen: '⚖️ Dataskyddsjuristen',
  ui_design:          '🎨 UI/Design-granskaren',
  frontend:           '🧱 Frontend-agenten',
  responsive:         '📐 Responsivitet & Mobil',
  accessibility:      '♿ Tillgänglighet',
  visual_qa:          '📸 Visuell QA-granskaren',
  datamigration:      '🔀 Datamigrationsarkitekten',
  api:                '📜 API-agenten',
  error_handling:     '🧯 Felhantering',
  edge_case:          '🪤 Edge-case-jägaren',
  code_quality:       '📋 Kodkvalitet',
  security:           '🔒 Säkerheten',
  hemlighetsvakten:   '🔑 Hemlighetsvakten',
  performance:        '⚡ Prestanda',
  scalability:        '📈 Skalbarhet',
  data_privacy:       '🛡️ Dataskydd',
  testing:            '🧪 Test-agenten',
  rotorsak:           '🔬 Rotorsaksanalytikern',
  backend:            '⚙️ Backend-agenten',
  devops:             '🚀 DevOps/CI-CD-agenten',
  ai_ml:              '🤖 AI/ML-granskaren',
  dokumentation:      '📖 Dokumentationsagenten',
  licens:             '📦 Licens & Supply chain',
  i18n:               '🌍 i18n-agenten',
  observability:      '📡 Observability-agenten',
  concurrency:        '🧵 Trådsäkerhetsagenten',
  krypto:             '🔐 Kryptoagenten',
  agent_arkitektur:   '🦷 Agentarkitekturagenten',
};
```

---

## T12 — _memory_gc_loop

**Fil:** `app.py`  
**Steg 1:** Lägg till konstanter nära toppen:

```python
_MAX_PROGRESS_AGE_S = 3600   # 1 timme
_MAX_RUN_RESULTS    = 200
```

**Steg 2:** Lägg till funktionen:

```python
async def _memory_gc_loop() -> None:
    """Bakgrundsloop som rensar gamla _progress- och _RUN_RESULTS-poster."""
    while True:
        await asyncio.sleep(300)   # var 5:e minut
        now = time.time()
        stale = [k for k, v in _progress.items()
                 if now - v.get("_ts", now) > _MAX_PROGRESS_AGE_S]
        for k in stale:
            _progress.pop(k, None)
        if len(_RUN_RESULTS) > _MAX_RUN_RESULTS:
            overflow = len(_RUN_RESULTS) - _MAX_RUN_RESULTS
            for k in list(_RUN_RESULTS.keys())[:overflow]:
                _RUN_RESULTS.pop(k, None)
```

**Steg 3:** I `startup()`, lägg till:
```python
asyncio.create_task(_memory_gc_loop())
```

**Steg 4:** Varje ställe `_progress[key]` sätts — lägg till:
```python
_progress[key]["_ts"] = time.time()
```

---

## T13 — Path traversal guard i build_queue_result()

**Fil:** `app.py`  
**Sök:** `ref = f"{item_id}_{attempt}.json"` (rad ~679)

```python
# Ersätt:
ref = f"{item_id}_{attempt}.json"
path = BUILD_RESULTS_DIR / ref

# Med:
ref = f"{item_id}_{attempt}.json"
path = (BUILD_RESULTS_DIR / ref).resolve()
if not str(path).startswith(str(BUILD_RESULTS_DIR.resolve())):
    raise HTTPException(400, "Otillåten sökväg")
```

---

## T14 — request_disabled whitelist i /api/review

**Fil:** `app.py`  
**Sök:** `request_disabled = payload.get("disabled_agents") or []`

```python
# Ersätt:
request_disabled = payload.get("disabled_agents") or []

# Med:
_ALL_AGENT_IDS = set(SPECIALIST_AGENTS)
request_disabled = [
    a for a in (payload.get("disabled_agents") or [])
    if isinstance(a, str) and a in _ALL_AGENT_IDS
]
```

---

## T15 — Byte-gräns för bilder i review()

**Fil:** `app.py`  
**Sök:** `images = [i for i in images if isinstance(i, str) and i.startswith("data:image")][:6]`

```python
MAX_IMAGE_BYTES = 8_000_000  # 8 MB per bild

images = [
    i for i in images
    if isinstance(i, str)
    and i.startswith("data:image")
    and len(i.encode()) <= MAX_IMAGE_BYTES
][:6]
```

---

## T16 — model-fält längdvalidering i post_settings()

**Fil:** `app.py`  
**Sök:** `if "model" in payload: s["model"] = payload["model"]`

```python
if "model" in payload:
    m = payload["model"]
    if not isinstance(m, str) or len(m) > 120:
        raise HTTPException(400, "Ogiltigt modellnamn")
    s["model"] = m
```

---

## T17 — _SEVERITY_GUIDE: lägg till motivering

**Fil:** `app.py`  
**Sök:** `_SEVERITY_GUIDE` (rad ~1010)

Nuläge: `{"status", "findings", "severity", "suggestions"}`  
Uppdatera till att inkludera `motivering` i prompts som refererar schemat:

```python
# I prompt-strängen för _SEVERITY_GUIDE, lägg till:
"motivering": "Kort motivering på svenska till allvarlighetsbedömningen"
```

---

## T18 — Per-projekt agent-config UI (frontend)

**Fil:** `index.html`  
**Förutsättning:** Backend `/api/projects/{id}/settings` finns redan ✅

Lägg till agent-toggle-lista i projektets settings-modal:

```html
<div class="form-group">
  <label>Aktiverade agenter</label>
  <div id="agentToggleList" class="agent-toggle-list"></div>
</div>
```

```css
.agent-toggle-list {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: .25rem; max-height: 300px; overflow-y: auto;
  padding: .5rem; border: 1px solid var(--border, #333);
  border-radius: 6px;
}
.agent-toggle { display: flex; align-items: center; gap: .4rem;
  font-size: .8rem; cursor: pointer; }
```

```javascript
async function renderAgentToggles(projectId) {
  const resp = await fetch(`/api/projects/${projectId}/settings`);
  const settings = await resp.json();
  const disabled = new Set(settings.disabled_agents || []);
  const container = document.getElementById('agentToggleList');
  container.innerHTML = Object.entries(AGENT_DISPLAY_NAMES).map(([id, label]) => `
    <label class="agent-toggle">
      <input type="checkbox" value="${id}"
             ${disabled.has(id) ? '' : 'checked'}
             onchange="toggleAgent('${projectId}', '${id}', this.checked)">
      ${label}
    </label>
  `).join('');
}

async function toggleAgent(projectId, agentId, enabled) {
  await fetch(`/api/projects/${projectId}/settings`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({agent_id: agentId, enabled})
  });
}
```

---

## BYGGORDNING (rekommenderad sprint)

**Sprint 1 — Git + säkerhet (gör ASAP)**  
T0 → T13 → T14 → T15 → T16 → T10

**Sprint 2 — Kärnan av chatbox**  
T4 → T5 → T6 → T7 → T8 → T4b → T12

**Sprint 3 — UX + polish**  
T11 → T9 → T2 → T3 → T17

**Sprint 4 — Per-projekt konfiguration**  
T18

---

*Fil genererad automatiskt av Claude — uppdatera alltid mot faktisk app.py/index.html-status.*
