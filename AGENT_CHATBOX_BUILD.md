# Build: Embedded Agent Chat Box with Auto-Build Loop

## Context — read before touching any file

This is a FastAPI + vanilla-JS app running on port 8001.
- `app.py` — ~4025 lines. FastAPI backend. Do NOT read the whole file. Use `search_file` to find sections.
- `index.html` — ~4076 lines. Single-file frontend. Same rule.

### What already exists (do not re-implement)

| Thing | Where |
|---|---|
| `get_client()` | app.py line ~126 — returns `anthropic.Anthropic(api_key=..., timeout=120.0)` |
| `anthropic` import | app.py line 17 — already imported |
| `executor` | app.py line ~27 — ThreadPoolExecutor(max_workers=80) |
| `load_settings()` | app.py — returns dict from settings.json |
| `_queue_load()` / `_queue_write()` / `_queue_lock` | app.py — use these for all queue reads/writes |
| `build_project_context(profile)` | app.py line ~1916 — generates tech-stack context string |
| `github_fetch(payload)` | app.py line ~3650 — async FastAPI handler, callable directly as `await github_fetch({"repo":..., "branch":...})` |
| `build_queue_review(item_id, payload)` | app.py line ~3440 — async handler, callable directly |
| `build_queue_result(item_id, payload)` | app.py line ~648 — async handler, callable directly |
| `BASE_DIR` | app.py line 47 — `Path(__file__).parent` |
| FastAPI imports | app.py line ~14 — `from fastapi.responses import FileResponse, JSONResponse` — add `StreamingResponse` here |

### Build queue state machine (do not change)

`kö` → **`byggs`** (set by `/send`) → `klar` | `behover_dig`

The `/send` endpoint is already called by `startBuild()` in the frontend before the agent starts. By the time the SSE stream opens, the item is already in `byggs` status.

### Current "byggs" UI (what we are replacing)

In `renderQueueBox()` (index.html ~line 2039), when `it.status === 'byggs'`, the card currently shows:
- "🔍 Kontrollera" button — fetches GitHub code + calls `/review` manually
- "📋 ...eller klistra in koden själv" button — paste flow
- "↩ Tillbaka till kö" button — keep this

After this build: replace the first two buttons with "💬 Öppna i chat-panel" (calls `openBuilderPanel(it.id)` without restarting the build).

Also in `startBuild()`: replace the clipboard/toast logic with `openBuilderPanel(item_id, data.job)`.

Also change the helper text on the `kö` card from `"Specen kopieras — klistra in i din byggare"` to `"Agenten bygger direkt i chat-panelen"`.

---

## What to Build

### 1. Server-side state (add at module level in app.py)

```python
# Builder agent state — keyed by item_id
_active_builders: dict[str, asyncio.Task] = {}       # running SSE tasks
_builder_histories: dict[str, list[dict]] = {}        # message history for reconnect
_builder_lock = threading.Lock()
```

### 2. SSE endpoint — `GET /api/builder/stream/{item_id}`

```python
from fastapi.responses import StreamingResponse  # add to existing import line
from fastapi import Request
import subprocess

@app.get("/api/builder/stream/{item_id}")
async def builder_stream(item_id: str, request: Request, profile: str = "{}"):
```

This is a **Server-Sent Events** endpoint. Returns `StreamingResponse` with `media_type="text/event-stream"`.

The response is an `async def` generator that yields SSE frames:

```python
async def generate():
    yield f"data: {json.dumps({'type': 'status', 'text': 'Startar...'})}\n\n"
    # ... all events below ...
    # keepalive every 15 seconds while waiting:
    yield ": keepalive\n\n"
```

**Full flow inside the generator:**

#### Step A — Pre-flight (stream status events as each check runs)

```python
profile_dict = json.loads(profile) if profile else {}
s = load_settings()

# 1. Resolve local repo path
repo_path = Path(profile_dict.get("local_path") or s.get("local_path") or str(BASE_DIR))
if not repo_path.exists():
    yield _sse_err("Lokal sökväg finns inte: " + str(repo_path)); return

# 2. Load queue item
with _queue_lock:
    items = _queue_load()
    item = next((i for i in items if i.get("id") == item_id and not i.get("deleted_at")), None)
if not item:
    yield _sse_err("Ärende hittades inte."); return
if item["status"] != "byggs":
    yield _sse_err(f"Felaktig status: {item['status']} — förväntat 'byggs'."); return

# 3. git fetch + pull
r = _run_cmd("git fetch origin", repo_path)
yield _sse_tool("run_cmd", "git fetch origin", r)
r = _run_cmd("git pull --ff-only", repo_path)
yield _sse_tool("run_cmd", "git pull --ff-only", r)
# Note: if pull fails (diverged), log warning but continue — don't block the build
```

#### Step B — Agentic loop

Use `anthropic.AsyncAnthropic` (NOT the sync `get_client()`):

```python
api_key = load_settings().get("api_key", "")
client = anthropic.AsyncAnthropic(api_key=api_key, timeout=120.0)
```

System prompt:

```python
system = f"""You are an expert software engineer implementing a spec exactly as written.

Project context:
{build_project_context(profile_dict)}

Rules:
- app.py and index.html are ~4000 lines each. ALWAYS use search_file first to locate
  relevant sections, then read_file with line_start/line_end. Never read a large file in full.
- Make minimal, focused changes. Do not refactor code outside the spec scope.
- Match the existing code style exactly.
- Do NOT start the server. Do NOT install packages. Do NOT modify .git/ directly.
- When all changes are done, call report_done with a summary of what was built.
"""
```

Initial messages:

```python
full_prompt = (
    (item.get("last_verdict") and item["last_verdict"].get("kvarstaende") and
     "FÖREGÅENDE FÖRSÖK UNDERKÄNDES. Kvarstående:\n" +
     "\n".join(f"- {k}" for k in item["last_verdict"]["kvarstaende"][:10]) + "\n\n")
    or ""
) + item["spec_markdown"] + (item.get("byggsatt_used") and "\n\n" + str(item["byggsatt_used"]) or "")

messages = [{"role": "user", "content": full_prompt}]
# Save to history for reconnect
_builder_histories[item_id] = messages.copy()
```

**Tool loop** — max 30 turns:

```python
MAX_TURNS = 30
for turn in range(MAX_TURNS):
    # Check client disconnect
    if await request.is_disconnected():
        break

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=system,
        tools=BUILDER_TOOLS,   # see section 4
        messages=messages,
    )

    # Stream text blocks immediately
    assistant_content = []
    for block in response.content:
        if block.type == "text":
            yield _sse({"type": "text", "text": block.text})
            assistant_content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            assistant_content.append(block.model_dump())

    messages.append({"role": "assistant", "content": assistant_content})
    _builder_histories[item_id] = messages.copy()

    # Stop conditions
    if response.stop_reason == "end_turn":
        break
    if response.stop_reason != "tool_use":
        break

    # Execute tool calls
    tool_results = []
    done = False
    for block in response.content:
        if block.type != "tool_use":
            continue
        name = block.name
        inp = block.input

        yield _sse({"type": "tool_start", "name": name, "input": inp})

        if name == "report_done":
            done = True
            tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                  "content": "Acknowledged. Proceeding to commit locally."})
            yield _sse({"type": "tool_result", "name": name, "preview": inp.get("summary","")})
            break  # stop executing further tools
        else:
            result = await _exec_tool(name, inp, repo_path)
            preview = str(result)[:300]
            tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                  "content": str(result)})
            yield _sse({"type": "tool_result", "name": name, "preview": preview})

    messages.append({"role": "user", "content": tool_results})
    _builder_histories[item_id] = messages.copy()

    if done:
        break
else:
    yield _sse({"type": "status", "text": "⚠️ Max antal varv nått (30) — avbryter."})
```

#### Step C — Git commit (ALDRIG push — det gör bara användaren)

**PRINCIPREGEL: Systemet pushar ALDRIG automatiskt till git. Push är alltid en manuell
användaråtgärd. Agenten committar lokalt, sedan väntar systemet på att användaren pushar.**

Only runs after `report_done` or natural loop end:

```python
yield _sse({"type": "status", "text": "📦 Committar ändringar lokalt..."})

commit_msg = f"feat: {item['title'][:72]}"
_run_cmd("git add -A", repo_path)
r = _run_cmd(f'git commit -m "{commit_msg}"', repo_path)
yield _sse_tool("run_cmd", f"git commit -m ...", r)

if "nothing to commit" in r.lower():
    yield _sse({"type": "status", "text": "ℹ️ Inga filändringar att committa."})
    commit_sha = ""
    diff = ""
else:
    sha_r = _run_cmd("git rev-parse HEAD", repo_path)
    commit_sha = sha_r.strip()

    diff_r = _run_cmd("git diff HEAD~1", repo_path)
    diff = diff_r[:400_000]

    stat_r = _run_cmd("git diff HEAD~1 --stat", repo_path)
    yield _sse({"type": "status", "text": f"📋 Commit klar:\n{stat_r[:600]}"})
```

#### Step D — Vänta på att användaren pushar

Efter commit streamas ett `"ready_to_push"`-event med commit-sha och diff-stat.
Ingen automatisk push sker. Frontenden visar en "Pusha & granska"-knapp.
När användaren klickar den, pushar de själva via sin terminal ELLER via en separat
`POST /api/builder/push/{item_id}` som kräver explicit användarinteraktion (knappklick).

**OBS: `POST /api/builder/push/{item_id}` KRÄVER ett explicit `confirmed: true` i body**
**— det ska aldrig kallas automatiskt från frontend-kod.**

```python
yield _sse({
    "type": "ready_to_push",
    "commit_sha": commit_sha,
    "diff_stat": stat_r[:600],
    "text": "✅ Agenten är klar och har committat lokalt. Pusha till GitHub och klicka sedan 'Kontrollera mot GitHub' för att granska.",
})
# SSE-strömmen stängs här. Användaren tar över.
return
```

#### Step E — Granskning (efter att användaren har pushat)

Granskningen sker precis som idag via den befintliga `kontrolleraBuild(id)`-funktionen
i frontend — användaren klickar "Kontrollera mot GitHub" efter sin push.
Ingen förändring behövs i `/review`-endpointen.

```python
# INGET nytt granskning-steg här — det är samma manuella "Kontrollera"-knapp som idag.
# Separationen är viktig: push = användarval, granskning = konsekvent manuell trigger.
```

#### Step E — Follow-up message handling

If the user types a follow-up in the chat while `behover_dig`, a `POST /api/builder/followup/{item_id}` endpoint receives `{"message": "..."}`, appends it to `_builder_histories[item_id]`, resets item to `kö`, and the frontend calls `startBuild(item_id)` which calls `/send` (which rewrites the spec with kvarstaende) and then re-opens the SSE stream.

For mid-build follow-ups (while `byggs`), append to `_builder_histories[item_id]` and inject as a new user message in the next iteration of the tool loop.

### 3. Cancel endpoint

```
DELETE /api/builder/stream/{item_id}
```

```python
@app.delete("/api/builder/stream/{item_id}")
async def cancel_builder(item_id: str):
    task = _active_builders.pop(item_id, None)
    if task:
        task.cancel()
    with _queue_lock:
        items = _queue_load()
        it = next((i for i in items if i.get("id") == item_id), None)
        if it and it["status"] == "byggs":
            it["status"] = "kö"
            _queue_log(it, "avbruten", "manuellt")
            _queue_write(items)
    _builder_histories.pop(item_id, None)
    return {"ok": True}
```

Wrap the SSE generator in an `asyncio.Task` and store it:

```python
# At the start of builder_stream():
    task = asyncio.current_task()
    _active_builders[item_id] = task
try:
    async for chunk in generate():
        yield chunk
finally:
    _active_builders.pop(item_id, None)
```

---

## Kända brister och nödvändiga förbättringar

Dessa måste åtgärdas som del av detta bygge eller som separata ärenden direkt efteråt.

---

### SÄKERHET

#### S1 — Ta bort `profile` som URL-parameter (KRITISK)

**Problem:** `profile: str = "{}"` som query-param exponerar github_token och andra
hemligheter i plain text i uvicorn-accessloggar och eventuella proxy-loggar.

**Fix:** Ta bort `profile`-parametern helt. Allt SSE-endpointen behöver finns server-side:
- `local_path` → `load_settings().get("local_path", str(BASE_DIR))`
- `repo` / `branch` → spara i `item["repo"]` vid `/send` (job-objektet har det redan — persistera det)
- `project_context` → spara i `item["project_context"]` vid `/send` (se I2 nedan)

Ny signatur:
```python
@app.get("/api/builder/stream/{item_id}")
async def builder_stream(item_id: str, request: Request):
```

Frontend `connectBuilderStream()`:
```javascript
_builderEventSource = new EventSource(`/api/builder/stream/${item_id}`);
// Ingen ?profile=... parameter
```

#### S2 — `run_cmd` whitelist måste implementeras server-side (KRITISK)

**Problem:** Spec nämner whitelist men `_exec_tool` är inte implementerat. Utan det kan
en spec köra godtyckliga shell-kommandon.

**Implementation:**
```python
_CMD_WHITELIST = ("git ", "python --version", "where python", "dir ", "echo ")
_CMD_BLACKLIST = ("uvicorn", "python app.py", "start ", "curl ", "wget ",
                  "rm -rf", "del /s", "format ", "shutdown", "taskkill")

def _safe_run_cmd(command: str, repo_path: Path) -> str:
    cmd_lower = command.strip().lower()
    if any(cmd_lower.startswith(b) for b in _CMD_BLACKLIST):
        return f"[BLOCKERAT] Ej tillåtet: {command[:80]}"
    if not any(cmd_lower.startswith(w) for w in _CMD_WHITELIST):
        return f"[BLOCKERAT] Matchar inte whitelist. Tillåtna prefix: {', '.join(_CMD_WHITELIST)}"
    result = subprocess.run(
        command, shell=True, cwd=str(repo_path),
        capture_output=True, text=True, timeout=60
    )
    return (result.stdout + result.stderr).strip()[:4000]
```

#### S3 — `write_file` path traversal-skydd (KRITISK)

**Problem:** Agenten kan skriva `path: "../../secrets.txt"` och nå filer utanför repot.

**Fix i `_exec_tool` för write_file OCH read_file:**
```python
resolved = (repo_path / inp["path"]).resolve()
if not str(resolved).startswith(str(repo_path.resolve())):
    return "[BLOCKERAT] Sökvägen pekar utanför repot."
```

---

### ROBUSTHET

#### R1 — `finally`-block i SSE-generatorn

`_active_builders` rensas aldrig om generatorn kraschar. Wappa hela generate()-logiken:
```python
try:
    # ... all generator logic ...
finally:
    _active_builders.pop(item_id, None)
```

#### R2 — `_builder_histories` minnesbegränsning

Dict växer obegränsat. Kapa vid 50 entries:
```python
MAX_HISTORIES = 50
if len(_builder_histories) >= MAX_HISTORIES:
    oldest = next(iter(_builder_histories))
    del _builder_histories[oldest]
_builder_histories[item_id] = messages.copy()
```

#### R3 — Reconnect vid server-restart

`_builder_histories` försvinner vid server-restart. Om reconnect sker utan historik,
streama ett tydligt meddelande istället för tom panel:
```python
if item_id not in _builder_histories:
    yield _sse({"type": "status", "text":
        "⚠️ Serverhistoriken är borta (omstart?). Kontrollera git-loggen:\n"
        "• Har agenten committat? → pusha manuellt + klicka 'Kontrollera mot GitHub'\n"
        "• Inget committat? → klicka 'Tillbaka till kö' och starta om"})
    return
```

#### R4 — Pre-build WIP-commit om dirty tree

Om repot har uncommittade ändringar INNAN agenten startar — gör WIP-commit
(INTE stash — stash kan orsaka konflikter vid pop):
```python
dirty = _safe_run_cmd("git status --porcelain", repo_path)
if dirty.strip():
    yield _sse({"type": "status", "text": "📦 Committar befintliga ändringar som WIP..."})
    _safe_run_cmd("git add -A", repo_path)
    _safe_run_cmd(f'git commit -m "wip: pre-agent [{item["title"][:50]}]"', repo_path)
```

#### R5 — Max-turns: commita ändå det som gjorts

Om agenten når MAX_TURNS (30) utan `report_done`, fall igenom till Step C:
```python
else:  # for/else — loop nådde max utan break
    yield _sse({"type": "status", "text":
        "⚠️ Max 30 varv nått — committar ändå det som gjorts."})
    # fall through till Step C
```

#### R6 — `read_file` 12k-gräns måste enforças server-side

Promptinstruktionen räcker inte. Enforça i `_exec_tool`:
```python
MAX_READ_CHARS = 12_000
lines = content.splitlines()[line_start:line_end]
result = "\n".join(lines)
if len(result) > MAX_READ_CHARS:
    result = result[:MAX_READ_CHARS]
    result += "\n[TRUNKERAD — använd line_start/line_end för att läsa vidare]"
```

---

### INSTÄLLNINGAR

#### I1 — `local_path` saknas i backend och UI

**`app.py` → `load_settings` defaults:**
```python
"local_path": str(BASE_DIR),
```

**`app.py` → `post_settings`:**
```python
if "local_path" in payload:
    s["local_path"] = payload["local_path"]
```

**`index.html` → settings-modal HTML** (efter selfRepoInput-blocket):
```html
<div class="form-group">
  <label>Lokal sökväg till repo</label>
  <input type="text" id="localPathInput" placeholder="C:\innob-agent\prompt-team"
         style="font-family:monospace;font-size:12px;">
  <div style="font-size:11px;color:var(--text3);margin-top:4px;">
    Mappen agenten läser/skriver filer i. Standard = samma mapp som app.py.
  </div>
</div>
```

**`index.html` → `openSettings()`:**
```javascript
document.getElementById('localPathInput').value = s.local_path || '';
```

**`index.html` → `saveSettings()`:**
```javascript
payload.local_path = document.getElementById('localPathInput').value.trim();
```

#### I2 — Spara `project_context` i queue-itemet vid `/send` (kopplat till S1)

SSE-endpointen behöver project_context utan att få profilen via URL.
I `send_build_queue_item`, efter att `job` är byggt:
```python
item["project_context"] = job["project_context"]
_queue_write(items)
```
I SSE-endpointen:
```python
system = f"...\n\nProject context:\n{item.get('project_context', '')}\n..."
```

#### I3 — Byggagentens modell ska vara konfigurerbar

Lägg till i `_DEFAULT_AGENT_MODELS`:
```python
"builder": "anthropic/claude-sonnet-4.6",
```

I SSE-endpointen:
```python
raw_model = get_agent_model("builder", load_settings().get("model", "claude-sonnet-4-6"))
# AsyncAnthropic vill ha "claude-sonnet-4-6", inte "anthropic/claude-sonnet-4-6"
builder_model = raw_model.replace("anthropic/", "")
```

Visa i settings-UI:
```javascript
builder: '🤖 Byggagenten',   // lägg till i AGENT_DISPLAY_NAMES
```

---

### UX

#### U1 — Panel efter `ready_to_push`

När `ready_to_push`-eventet tas emot ska panelen visa ett tydligt hand-off-läge:
```
✅ Agenten är klar — commit [sha] gjord lokalt.

Nästa steg:
  1. git push origin main   (i din terminal)
  2. Klicka "🔍 Kontrollera mot GitHub" på kortet

```
Spinner stängs. "Avbryt"-knappen ersätts av "Stäng panel".
Panelen förblir öppen tills användaren stänger den.

#### U2 — Follow-up: använd INTE `/send` för mitt-i-bygget-meddelanden

Nuvarande spec säger felaktigt att follow-up → `startBuild()` → `/send`.
Det skapar nytt `attempt_nr` och skriver om specen — fel för mid-build input.

Korrekt uppdelning:
- **Mid-build** (status = `byggs`): `POST /api/builder/followup/{item_id}` med
  `{"message": "..."}` → append till `_builder_histories[item_id]` → injiceras i
  pågående tool-loop som ny user-message. **Ingen `/send`, inget nytt attempt_nr.**
- **Post-underkänt retry** (status = `behover_dig`): `startBuild()` → `/send` som vanligt.
  Det är det enda fallet där spec skrivs om och nytt attempt_nr sätts.

#### U3 — `kö`-kortets hjälptext

Ändra från:
```
"Specen kopieras — klistra in i din byggare"
```
Till:
```
"Agenten bygger direkt i chat-panelen"
```

---

## Iteration 2 — Ytterligare fynd

---

### ARKITEKTUR

#### A1 — Projekt lever i localStorage — inte på servern (viktigt att förstå)

`getActiveProject()` läser från `localStorage`. Servern vet INTE vilka projekt som finns.
Det påverkar direkt hur S1 (ta bort profile från URL) löses:

- Vid `/send` skickar frontend redan hela profilen i POST-bodyn — servern har den där
- **Lösnignen:** I `send_build_queue_item`, persistera till queue-itemet:
  ```python
  item["repo"]            = {"name": profile.get("repo",""), "branch": profile.get("branch","main")}
  item["project_context"] = job["project_context"]   # redan i job — spara till item också
  _queue_write(items)
  ```
- SSE-endpointen kan sedan läsa `item["repo"]` och `item["project_context"]` direkt.
  `local_path` kommer alltid från `load_settings()` — aldrig från klienten.

#### A2 — `target_builder` styr byggvägen — inte bara spec-format

`byggsatt.target_builder` i projektprofilen är redan satt till `'claude_code'` för
main-projektet. Det styr idag bara hur specen skrivs (via `_BUILDER_DIRECTIVE`).

**Efter detta bygge:** `startBuild()` ska kolla `target_builder` och välja rutt:
```javascript
async function startBuild(id, btn) {
  // ... /send-anrop som vanligt ...
  const builder = getActiveProject()?.profile?.byggsatt?.target_builder || 'manniska';
  if (builder === 'claude_code') {
    openBuilderPanel(item_id, data.job);   // nytt: agent-panelen
  } else {
    // befintligt urklipp-flöde för lovable/cursor/v0/manniska
    await navigator.clipboard.writeText(spec).catch(() => {});
    showToast(...);
  }
}
```
Urklipp-flödet ska alltså BEVARAS för andra builders — inte tas bort.

---

### SÄKERHET (ny)

#### S4 — `git fetch` / `git pull` ska hoppas över om inget remote finns

Om `local_path`-repot inte har något remote (t.ex. ett nyskapat lokalt repo) kraschar
`git fetch origin` med ett fel som stoppar builden.

**Fix — kolla om remote finns innan fetch/pull:**
```python
remote_check = _safe_run_cmd("git remote get-url origin", repo_path)
has_remote = "fatal" not in remote_check.lower() and remote_check.strip()
if has_remote:
    r = _safe_run_cmd("git fetch origin", repo_path)
    yield _sse_tool("run_cmd", "git fetch origin", r)
    r = _safe_run_cmd("git pull --ff-only", repo_path)
    yield _sse_tool("run_cmd", "git pull --ff-only", r)
else:
    yield _sse({"type": "status", "text": "ℹ️ Inget remote — hoppar över fetch/pull."})
```

---

### ROBUSTHET (ny)

#### R7 — SSE keepalive måste vara en parallell task, inte inline

Anthropic-anrop tar 30–90s. Under den tiden skickas ingen SSE-data → proxies och
browsers stänger anslutningen.

**`": keepalive\n\n"` kan inte yieladas inline** — generatorn är blockerad på `await`.
Rätt mönster: wrappa API-anropet i en `asyncio.Task` och skicka keepalives under väntan:

```python
api_task = asyncio.create_task(client.messages.create(
    model=builder_model, max_tokens=8192,
    system=system, tools=BUILDER_TOOLS, messages=messages,
))
# Skicka keepalive var 15:e sekund tills svaret kommer
while not api_task.done():
    try:
        await asyncio.wait_for(asyncio.shield(api_task), timeout=15)
        break
    except asyncio.TimeoutError:
        yield ": keepalive\n\n"

response = api_task.result()  # hämta resultatet när klart
```

#### R8 — Cancel via `asyncio.Event` är säkrare än `Task.cancel()`

`task.cancel()` kastar `CancelledError` i generatorn vid godtycklig await — kan
korrumpera pågående filskrivning. Använd en avbrytsignal istället:

```python
# Modul-nivå
_cancel_flags: dict[str, asyncio.Event] = {}

# I generatorn — kontrollera i varje loop-varv
if _cancel_flags.get(item_id, asyncio.Event()).is_set():
    yield _sse({"type": "status", "text": "🛑 Bygget avbröts."})
    return

# I cancel_builder()-endpointen
flag = asyncio.Event()
flag.set()
_cancel_flags[item_id] = flag
# cleanup i generatorns finally:
_cancel_flags.pop(item_id, None)
```

#### R9 — `.gitignore` saknar test-artefakter

Lägg till i `.gitignore`:
```
intrim_result.json
test_intrim.py
AGENT_CHATBOX_BUILD.md
```
`AGENT_CHATBOX_BUILD.md` är en intern byggspecifikation — den ska inte committas till
main (innehåller råd om säkerhetshål). Alternativt: flytta till `_docs/`-mapp och lägg
till `_docs/` i `.gitignore`.

---

### UX (ny)

#### U4 — "Kontrollera"-knappens text ska sätta förväntningen rätt

Efter `ready_to_push` är "Kontrollera mot GitHub"-knappen redan rätt knapp att klicka —
men texten avslöjar inte att push krävs först. Ändra texten för `byggs`-statusen:

```javascript
// I renderQueueBox(), byggs-grenen:
actions = `<button class="btn btn-primary"
  onclick="kontrolleraBuild('${it.id}', this)"
  title="Pusha till GitHub först, klicka sedan här">
  🔍 Pusha → Kontrollera mot GitHub
</button>`
```

#### U5 — Urklipp-knappen ska BEVARAS för andra builders

Befintlig `buildResultModal` (klistra in resultatet manuellt) och urklippsflödet i
`startBuild()` ska inte tas bort. De ska fortsätta fungera när `target_builder` ≠ `claude_code`.
Spec-filen ska inte säga "ta bort urklipp" utan "flytta urklipp-logiken till else-grenen".

---

## Iteration 3 — Fynd från KID_USER_PROMPT.md och ARKITEKTUR_ANALYS.md

Dessa filer är nya sedan förra iterationen och innehåller kritiska krav och systemfynd.
Alla agenter som bygger i detta projekt ska läsa `KID_USER_PROMPT.md` FÖRST.

---

### PRIMÄRANVÄNDARENS KRAV (KID_USER_PROMPT.md)

#### K1 — Chat-panelens meddelanden måste vara barnvänliga (KRITISK)

Den primära användaren är 10 år. Chatten ska aldrig visa tekniska termer.

**Vad agenten gör internt (dolt eller kollapsbart) vs vad användaren ser:**

| Internt (dölj eller kollaps) | Visa istället |
|---|---|
| `tool_use: search_file {pattern: ...}` | `🔧 Söker i koden...` |
| `tool_use: read_file {path: app.py, line_start: 200}` | `📖 Läser app.py...` |
| `tool_use: write_file {path: index.html}` | `✏️ Skriver index.html...` |
| `tool_use: run_cmd {command: git add -A}` | (visa inget — git-kommandon är alltid dolda) |
| `git fetch origin` / `git pull` / `git commit` | (visa aldrig för användaren) |
| `SSE stream connected` | (visa aldrig) |
| `Pre-flight checks` | `🔍 Förbereder...` |
| `ready_to_push` | `✅ Klart! Jag har sparat ändringarna.` |
| `error: git diff HEAD~1 failed` | `⚠️ Hmm, något gick fel. Försöker igen... 🔄` |

**Implementation i `handleBuilderEvent()` (frontend):**
```javascript
function handleBuilderEvent(evt) {
  if (evt.type === 'text') {
    appendBuilderMessage('agent', evt.text);
  } else if (evt.type === 'tool_start') {
    const friendly = _TOOL_LABELS[evt.name] || '🔧 Arbetar...';
    appendBuilderMessage('tool', friendly);  // liten, grå rad — inte primär
  } else if (evt.type === 'tool_result') {
    // Visa INTE råresultatet — markera bara tool-raden som klar
    markLastToolDone();
  } else if (evt.type === 'status') {
    // Filtrera bort git-kommandon
    if (!_isGitCommand(evt.text)) {
      appendBuilderMessage('system', evt.text);
    }
  } else if (evt.type === 'ready_to_push') {
    appendBuilderMessage('system', '✅ Klart! Jag har sparat ändringarna lokalt.');
    showPushInstructions();
  }
}

const _TOOL_LABELS = {
  read_file:   '📖 Läser filen...',
  write_file:  '✏️ Skriver filen...',
  search_file: '🔧 Söker i koden...',
  list_dir:    '📂 Tittar i mappen...',
  report_done: '💾 Sparar allt...',
  // run_cmd visas ALDRIG för användaren
};

function _isGitCommand(text) {
  return /^(git |📦 Committar|🚀 Pushar)/i.test(text.trim());
}
```

#### K2 — Byggkö-kortet ska använda barnvänliga texter

Uppdatera `renderQueueBox()` med dessa textbyten:

| Nuvarande text | Ny text |
|---|---|
| `"▶ Bygg nästa"` | `"▶ Bygg det här!"` |
| `"Agenten bygger direkt i chat-panelen"` | `"Tryck för att börja bygga 🚀"` |
| `"💬 Öppna i chat-panel"` | `"💬 Visa vad som händer"` |
| `"↩ Tillbaka till kö"` | `"← Avbryt, vänta istället"` |
| `"🔄 Skicka igen (specen skrivs om...)"` | `"🔄 Försök igen"` |
| Status `byggs`: `"Byggs"` | `"⏳ Håller på att byggas..."` |
| Status `behover_dig`: `"Behöver dig"` | `"🙋 Jag behöver din hjälp!"` |
| Status `klar`: `"Klar"` | `"✅ Klart!"` |
| Status `kö`: `"I kö"` | `"🕐 Väntar på sin tur"` |

#### K3 — Verktygsanrop ska vara kollapsade som standard

I chattpanelens CSS: tool-rader (`.builder-tool-row`) ska vara kompakta och grå,
inte expanderade med raw JSON. Visa bara ikonen + kortnamnet. Full detalj på hover/klick.

```css
.builder-tool-row {
  font-size: 11px;
  color: var(--text3);
  padding: 2px 8px;
  border-left: 2px solid var(--border);
  margin: 1px 0;
  cursor: pointer;
}
.builder-tool-row:hover { color: var(--text2); }
/* Expanderat state — visas bara om användaren klickar */
.builder-tool-row.expanded .tool-detail { display: block; }
.builder-tool-row .tool-detail { display: none; font-family: monospace; font-size: 10px; }
```

---

### KRITISKA SYSTEMPROBLEM (ARKITEKTUR_ANALYS.md)

#### C1 — Stale "byggs"-status blockerar hela kön vid omstart (KRITISK)

`startup()` återställer INTE items som fastnat i "byggs". En serveromstart under ett
pågående bygge låser hela byggkön permanent (WIP-limiten tillåter bara ett aktivt bygge).

**Fix — lägg till i `startup()`:**
```python
@app.on_event("startup")
async def startup():
    _migrate_sessions()
    # Återställ items som fastnat i "byggs" vid föregående körning
    with _queue_lock:
        items = _queue_load()
        reset_count = 0
        for it in items:
            if it.get("status") == "byggs" and not it.get("deleted_at"):
                it["status"] = "kö"
                _queue_log(it, "reset_after_restart", "server startade om under bygge")
                reset_count += 1
        if reset_count:
            _queue_write(items)
            logger.warning("[startup] %d item(s) återställda från 'byggs' till 'kö'", reset_count)
```

#### C2 — `reload=True` kraschar aktiva körningar (KRITISK)

`uvicorn.run(..., reload=True)` i `__main__`-blocket gör att servern startar om varje
gång en `.py`-fil sparas — inklusive om en agent skriver till en Python-fil under ett bygge.
Varje omstart tappar `_RUN_RESULTS`, `_progress` och `_builder_histories`.

**Fix — hitta `__main__`-blocket i app.py och ändra:**
```python
# Ändra reload=True → reload=False
uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=False)
```
Lägg en kommentar: `# reload=True bara vid lokal utveckling — aldrig i drift`

#### C3 — Hemlighetsvakten måste hårdblockera i agent-loopen

`hemlighetsvakten` returnerar UNDERKÄND om den hittar nycklar/credentials i koden.
Men idag hamnar det bara som ett P0-item i backloggen — inget stoppar ett push.

I agent-loopen: efter att `/review` är klart (när användaren klickar "Kontrollera"),
ska resultatet kontrolleras för hemlighetsvakten-fynd INNAN status sätts till `klar`:
```python
# I build_queue_review():
raw_items = (review_res.get("backlog_result") or {}).get("items", [])
# Secrets-block: hemlighetsvakten-fynd är icke-förhandlingsbara
secret_findings = [i for i in raw_items
                   if i.get("agent") == "hemlighetsvakten"
                   and i.get("status") != "GODKÄND"]
if secret_findings:
    is_klar = False
    verdict["kvarstaende"] = [f"🔐 HEMLIGHET HITTAD: {i.get('title','')}"
                               for i in secret_findings] + verdict.get("kvarstaende", [])
```

#### C4 — `hemlighetsvakten` och `dataskyddsjuristen` ska alltid köra (KRITISK)

`_QUICK_AGENT_IDS` exkluderar dessa agenter i snabbläge. En snabb iteration kan
pusha kod med exponerade API-nycklar eller GDPR-brott utan att de flaggas.

**Fix — hitta `_QUICK_AGENT_IDS` i app.py och lägg till:**
```python
# Dessa agenter kör ALLTID oavsett djupläge — de är snabba och icke-förhandlingsbara
_ALWAYS_RUN_AGENT_IDS = {"hemlighetsvakten", "dataskyddsjuristen"}
```
Modifiera `agents_for_mode()` att alltid inkludera `_ALWAYS_RUN_AGENT_IDS` oavsett `depth`.

#### C5 — Sessionsnamn ska baseras på tolkad idé

`auto_name()` tar råtextens första 7 ord → ger namn som `"itterera · 10 Jun"`.
`krav_result.get("tolkad_ide")` innehåller en meningsfull sammanfattning men används inte.

**Fix i `save_session()` / anropsplatsen:**
```python
# Om tolkad_ide finns och är < 60 tecken, använd den som sessionsnamn
if krav_result and krav_result.get("tolkad_ide", "").strip():
    name = krav_result["tolkad_ide"].strip()[:60]
else:
    name = auto_name(input_text)
```

#### C6 — `.gitignore` saknar flera filer (komplettering av R9)

Baserat på untracked files i `git status`, lägg till i `.gitignore`:
```
intrim_result.json
intrim_result_concrete.json
test_intrim.py
ARKITEKTUR_ANALYS.md
KID_USER_PROMPT.md
AGENT_CHATBOX_BUILD.md
```
Dessa är interna arbets- och testdokument som inte ska versionhanteras i main.

---

### REFERENS TILL FULLSTÄNDIG ANALYS

`ARKITEKTUR_ANALYS.md` innehåller ytterligare systemproblem (9a–9r) som är utanför
scope för detta bygge men ska åtgärdas som separata ärenden:
- 9a: sessions.json tidsbomb (>4MB, läses i minnet)
- 9b: Ingen autentisering
- 9c: Projekt i localStorage (ingen server-backup)
- 9o: Ingen semaphore på simultana granskningar
- 9p: build_queue.json/backlog.json tombstone-tillväxt
- 9r: reload=True i produktion (täckt i C2 ovan)

Dessa läggs som egna items i backloggen — inte i detta bygge.

---

## Iteration 4 — Fynd från remote merge 3654bd7 (feat/agent-audit-export)

*Datum: 2026-06-10 | 726 raders ändringar i app.py och index.html*

Mergen innehöll fyra förändringar som direkt påverkar byggagentens beteende.

---

### D1 — GitHub fetch-limiter höjda: 60k→400k total, 8k→200k per fil (INFO)

`github_fetch()` kan nu läsa hela `app.py` (~160k) och `index.html` (~175k) utan trunkering.
Tidigare var `search_file` + `read_file(line_start, line_end)` kritisk för att undvika 8k-stympade
filer. Det är fortfarande det föredragna mönstret (snabbare, billigare), men agenten kan nu
använda `github_fetch` som fallback om kontext är otillräcklig.

**Regel: `search_file` + `read_file(line_range)` är primär. Full-fil-läsning bara som fallback.**

---

### D2 — Resultatåterhämtning via `/api/review/result/{run_id}` (VIKTIG)

Granskningskörningar kan nu återhämtas om webbläsaren tappar anslutningen (~300s timeout i Chrome).
**Byggagenten ska skicka `run_id` som SSE-event** så att frontend kan visa "Visa resultat" vid refresh:

```python
# I Step E (granskning), efter att /review-anropet startat:
review_data = await build_queue_review(item_id, review_payload)
run_id = review_data.get("run_id") or review_data.get("id", "")
if run_id:
    yield _sse({"type": "review_started",
                "run_id": run_id,
                "recovery_url": f"/api/review/result/{run_id}",
                "text": "🔍 Granskning startad..."})
```

```javascript
// I frontend handleBuilderEvent():
case "review_started":
    sessionStorage.setItem('builder_recovery_' + currentItemId, JSON.stringify({
        run_id: msg.run_id, url: msg.recovery_url, ts: Date.now()
    }));
    break;
```

I `loadAttBygga()`: om `sessionStorage` har en `builder_recovery_<id>`-nyckel för ett
`byggs`-item och mergen är äldre än 30s — visa "📋 Visa granskningsresultat"-knapp som
hämtar recovery-URL:en.

---

### D3 — `.gitignore` — fullständig lista att patcha in en gång

Mergen lade till `intrim_result.json` och `ai_eval_results.json`. Följande saknas fortfarande:

```
# Test- och eval-artefakter
intrim_result_concrete.json
test_intrim.py

# Intern dokumentation (ska ej vara i main)
ARKITEKTUR_ANALYS.md
KID_USER_PROMPT.md
AGENT_CHATBOX_BUILD.md
```

Använd `patch_file` för att lägga till i slutet av `.gitignore` — kontrollera att raderna
inte redan finns innan patch appliceras (sök efter `AGENT_CHATBOX_BUILD.md` i filen).

---

### D4 — UI: `renderQueueBox()` kan ha ändrats av mergen (VERIFIERA)

Mergen ändrade UI för kodinmatning i Beställ-vyn. Byggagentens instruktion om att
ersätta knappar i `renderQueueBox()` "byggs"-grenen gäller fortfarande, men verifiera
att knapparna fortfarande heter/beter sig likadant efter mergen. Sök efter
`kontrolleraBuild` och `startBuild` i index.html för att bekräfta signaturer.

---

### D5 — Buggrapport-gate påverkar ej byggloopen (INFO)

`/api/review` kräver nu ≥20 tecken + ≥3 ord för buggrapporter. Gäller INTE
`granska_kod`-läget. Ingen kodändring krävs i byggagenten.

---

## Iteration 6 — Fynd från kodgranskning 2026-06-10

Dessa problem hittades vid manuell granskning av app.py och är åtgärdade i samma session.
Dokumenteras här för historik och för att undvika regression.

### AE. FIXAD — C1: startup() återställde inte 'byggs'-status (KRITISK)
**Status: åtgärdad 2026-06-10**

Items fastnade i `"byggs"` efter serveromstart. WIP-limiten tillåter bara ett aktivt
bygge per projekt — ett hängt item låste hela köprocessen permanent.

**Lösning:** `startup()` itererar nu `_queue_load()` och återställer alla `"byggs"` → `"kö"`
med log-post `"reset_after_restart"`.

---

### AF. FIXAD — C2: reload=True kraschade aktiva körningar (KRITISK)
**Status: åtgärdad 2026-06-10**

`uvicorn.run(..., reload=True)` startade om servern vid varje filsparning. Varje omstart
tappade `_RUN_RESULTS`, `_progress`, `_builder_histories`.

**Lösning:** `reload=False` med kommentar om manuell omstart vid kodbyte.

---

### AG. FIXAD — C4: hemlighetsvakten och dataskyddsjuristen hoppades över i snabbläge
**Status: åtgärdad 2026-06-10**

`_QUICK_AGENT_IDS` exkluderade dessa agenter i snabbläge — exponerade nycklar och
GDPR-brott gick igenom utan flaggning.

**Lösning:** `_ALWAYS_RUN_AGENT_IDS = {"hemlighetsvakten", "dataskyddsjuristen"}`.
Inkluderas alltid oavsett `depth` i `agents_for_mode()`.

---

### AH. FIXAD — C3: hemlighetsvakten var inte ett hårt stopp i build_queue_review
**Status: åtgärdad 2026-06-10**

Hemlighetsvarningar hamnade bara som P0 i backloggen. Inget stoppade status `"klar"`
trots exponerade credentials.

**Lösning:** `build_queue_review()` kontrollerar `secret_findings` direkt på agent-resultaten
(id=`hemlighetsvakten`). Om UNDERKÄND sätts `is_klar = False` oavsett P0-räkning.
`verdict["secrets_blocked"]` rapporteras.

---

### AI. FIXAD — I1: local_path saknades i settings
**Status: åtgärdad 2026-06-10**

Ingen `"local_path"`-nyckel i defaults → `Path(None)` → krasch vid byggagentstart.

**Lösning:** Default `"local_path": str(BASE_DIR)`. `post_settings()` sparar nyckeln.

---

### AJ. FIXAD — C5: sessionsnamn var råtextens första 7 ord
**Status: åtgärdad 2026-06-10**

`auto_name("itterera")` → `"itterera · 10 Jun"`. `krav_result["tolkad_ide"]` användes inte.

**Lösning:** Om `tolkad_ide` finns används den (max 60 tecken) som sessionsnamn.

---

### AK. FIXAD — Dead code: `_local_save` med missvisande docstring
**Status: borttagen 2026-06-10**

Funktionen deklarerades men anropades aldrig. Docstringen påstod felaktigt "Atomic-safe"
trots att `.tmp`-→-`.replace`-mönstret saknades. Borttagen — `_atomic_write()` är rätt.

---

### AL. Kvarstående: `auto_advance` och `builder_review_depth` i settings UI
Se AA. `local_path` är nu sparad i backend. Frontend-delen (checkbox + select i settings-modal) återstår.

### AM. Kvarstående: `project_context_snapshot` sparas inte vid /send
Se Z. `build_project_context(profile)` beräknas men sparas inte på queue-itemet. Kräver ändring i `send_build_queue_item`.

### AN. INFO: Supabase-anrop sker inte via polling
Alla Supabase-anrop sker on-demand och returnerar när de är klara. Ingen bakgrundstråd
pollar databasen. `/api/health` är enda endpointen som testar explicit — och den anropas
manuellt från UI. **Inga ändringar behövs** — detta är korrekt beteende. Noteras för att
förhindra "lösa polling"-refaktorering i framtida iterationer.

---

## Iteration 7 — Fynd från lokala uncommitted ändringar (working tree)

*Datum: 2026-06-10 | git diff HEAD — app.py (~180 rader ny kod), index.html (kritisk truncation)*
*OBS: Iteration 6 (ovan) dokumenterar fixes som redan är implementerade. Denna iteration täcker nya fynd därutöver.*

---

### E1 — `index.html` AVHUGGEN I WORKING TREE (KRITISK — BLOCKERANDE)

**Filen slutar med:** `updateActiveProjBadge(` — ingen avslutande parentes, ingen newline.

Saknar allt efter rad 4076:
- Avslutande `)` och `;` för `updateActiveProjBadge()`
- `loadHistory()` — historikfliken laddas inte
- `updateGithubSection()` — GitHub-raden initieras inte
- `refreshByggaBadge()` — tab-badge uppdateras inte
- `setTimeout(() => runHealthCheck(), 800)` — hälsokontroll körs aldrig
- `});` — stänger `ensureMainProject().then()`
- `});` — stänger `DOMContentLoaded`-lyssnaren
- Tangentbordsgenväg-lyssnaren (`Ctrl+Enter` → `runReview()`)
- Paste-lyssnaren (skärmdumpar från clipboard)
- Live reload-pollningen (`/api/version`)
- `</script>`, `</body>`, `</html>`

**Konsekvens:** JS-parsern kastar `SyntaxError: Unexpected end of input` → hela sidan är vit/tom.

**Vad som ska återställas** (det som togs bort, baserat på git diff HEAD):
```javascript
    updateActiveProjBadge();
    loadHistory();          // load AFTER project is set so filter is correct
    updateGithubSection();  // setup github row based on active project
    refreshByggaBadge();    // tab badge + attention banner
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

**Byggagenten ska verifiera** att `index.html` slutar med `</html>` som sista rad innan push.
Lägg till ett explicit kontrollsteg i `report_done`-verktyget:
```python
# I _exec_tool, "report_done"-grenen:
idx = repo_path / "index.html"
if idx.exists():
    last_line = idx.read_text(encoding="utf-8").rstrip().split("\n")[-1].strip()
    if last_line != "</html>":
        return {"error": f"index.html verkar avhuggen — sista raden är: {last_line!r}. "
                         "Filen är inte komplett. Åtgärda innan commit."}
```

---

### E2 — Redan implementerade fixes — se Iteration 6 (AE–AK)

Iteration 6 dokumenterar fullständigt vad som redan implementerats i working tree.
Sammanfattning av söktermer för att verifiera att kod inte dupliceras:

| Söksträng | Hittas i | Bekräftar |
|---|---|---|
| `reset_after_restart` | `startup()` | C1 implementerat |
| `secret_findings` | `build_queue_review()` | C3 implementerat |
| `_ALWAYS_RUN_AGENT_IDS` | modul-nivå | C4 implementerat |
| `_QUICK_AGENT_IDS \| always` | `agents_for_mode()` | C4 implementerat |
| `_tolkad` | `review()` | C5 implementerat |
| `"local_path"` | `load_settings()` och `post_settings()` | I1 implementerat |
| `_atomic_write` | modul-nivå | `_local_save` ersatt |

**Regel:** Sök alltid med `search_file` INNAN du skriver ny kod.

---

### E3 — Två nya specialistagenter tillagda (påverkar _DEFAULT_AGENT_MODELS)

Working tree har lagt till:

| ID | Namn | Emoji | Modell | Kör i |
|---|---|---|---|---|
| `concurrency` | Trådsäkerhetsagenten | 🧵 | gemini-2.5-flash | NY, GRANSKA, BUGG |
| `krypto` | Kryptoagenten | 🔐 | gemini-2.5-flash | NY, GRANSKA, BUGG |

**Byggagenten behöver veta detta för:**
1. `_DEFAULT_AGENT_MODELS` — dessa IDs finns redan, lägg inte till igen
2. `_QUICK_AGENT_IDS` — båda är redan tillagda i snabbläge
3. `AGENT_DISPLAY_NAMES` i index.html saknar troligtvis dessa — kontrollera och lägg till:
   ```javascript
   // I AGENT_DISPLAY_NAMES-objektet i index.html:
   "concurrency": "🧵 Trådsäkerhetsagenten",
   "krypto":      "🔐 Kryptoagenten",
   ```

---

### E4 — Utökade agent-modes i working tree

Flera agenter kör nu i fler modes (NY/GRANSKA/BUGG). Byggagentens spec berörs inte
direkt, men det bekräftar att systemet växer — `SPECIALIST_AGENTS`-arrayen är nu längre
än de ~29 agenter som nämns i Iteration 1. Sök alltid aktuellt antal:
```python
# Hur många agenter finns just nu?
search_file(pattern="\"id\":", path="app.py")  # räkna träffar i SPECIALIST_AGENTS-blocket
```

---

### E5 — Nya databas- och säkerhetskontroller (kontextuppdatering)

Working tree lade till följande kontroller i befintliga agenter. Nämns här som
referens — byggagenten förändrar inte dessa agenter.

**Databasagenten fick:**
- Connection pool — öppnas ny DB-connection per request?
- Query-timeout — saknas timeout på långkörande queries?
- Soft-delete-fallgrop — `is_deleted`-flagga utan partiellt index → full table scan?

**Säkerhetsagenten fick:**
- SSRF — kan servern göra HTTP-anrop till interna adresser baserat på user-input?
- OAuth/OIDC — valideras state-parameter, redirect_uri och token-audience korrekt?
- JWT — kontrolleras algoritm (alg:none-attack), expiry och signatur?
- Osäker deserialisering — pickle, YAML.load, eval på user-supplied data?
- Mass assignment — kan klienten sätta `is_admin`, `password_hash` via bulk-update?

**Arkitekturagenten fick:**
- Event-driven design — event sourcing/CQRS/message queues — osynliga temporala beroenden?
- Distribuerade system-fallgropar — split-brain, double-write, inconsistent reads?

---

### E6 — Sammanfattning: vad som återstår att bygga

Med working-tree-ändringarna är status:

| Komponent | Status |
|---|---|
| `byggs`→`kö` reset vid startup | ✅ Implementerat |
| `_ALWAYS_RUN_AGENT_IDS` | ✅ Implementerat |
| hemlighetsvakten hard-block | ✅ Implementerat |
| Sessionsnamn från `tolkad_ide` | ✅ Implementerat |
| `local_path` i settings | ✅ Implementerat |
| `_atomic_write()` (ersätter `_local_save`) | ✅ Implementerat |
| `concurrency` + `krypto` agenter | ✅ Implementerat |
| **`index.html` truncation — E1** | ❌ KRITISK — måste fixas |
| **AGENT_DISPLAY_NAMES saknar concurrency/krypto** | ❌ Saknas |
| **SSE endpoint `/api/builder/stream/{id}`** | ❌ Saknas (hela chatboxen) |
| **`#builderPanel` HTML + CSS + JS** | ❌ Saknas |
| `local_path` i inställnings-UI (index.html) | ❌ Saknas |
| `run_id` recovery-event i SSE (D2) | ❌ Saknas |
| `.gitignore` komplettering (D3) | ❌ Saknas |
turn ('\n---\n'.join(results) or '(no matches)')[:6000]
```

Use this directly in `_exec_tool` for `search_file` — no subprocess needed.

### H. Technical correction: `write_file` size guard and retry his
---

## Iteration 4 — Analys av commit f92c931 (vag-input-gate + motivering + fler agenter)

### F1 — 7 nya agenter saknas i `AGENT_DISPLAY_NAMES` (index.html)

Commit `f92c931` lade till följande specialistagenter i `SPECIALIST_AGENTS` (app.py):

| ID | Namn | Emoji | Djup/Snabb |
|---|---|---|---|
| `backend` | Backend-agenten | ⚙️ | SNABB |
| `devops` | DevOps/CI-CD-agenten | 🚀 | Djup only |
| `ai_ml` | AI/ML-granskaren | 🤖 | SNABB |
| `dokumentation` | Dokumentationsagenten | 📖 | Djup only |
| `licens` | Licensgranskaren | ⚖️ | Djup only |
| `i18n` | i18n-agenten | 🌍 | Djup only |
| `observability` | Observability-agenten | 📡 | Djup only |

`AGENT_DISPLAY_NAMES` i **index.html** (~rad 1357) saknar alla sju. Konsekvens:
- Settings-modal visar agent-ID (utan emoji/namn) för dessa i modellvalslistan
- Byggagenten ska lägga till dessa i `AGENT_DISPLAY_NAMES`:

```javascript
// Tillägg i AGENT_DISPLAY_NAMES-objektet (index.html ~rad 1357):
backend:       '⚙️ Backend-agenten',
devops:        '🚀 DevOps/CI-CD-agenten',
ai_ml:         '🤖 AI/ML-granskaren',
dokumentation: '📖 Dokumentationsagenten',
licens:        '⚖️ Licensgranskaren',
i18n:          '🌍 i18n-agenten',
observability: '📡 Observability-agenten',
```

`_QUICK_AGENT_IDS` (app.py) innehåller redan `backend` och `ai_ml` — OK.
`devops`, `dokumentation`, `licens`, `i18n`, `observability` kör bara i djupläge — ej i snabb.

---

### F2 — `motivering`-fält: redan implementerat i index.html

Commit `f92c931` lade till visning av `motivering` i agentkort och exporter i **index.html**.
Chatboxen ska respektera detta — när den renderar agent-resultat från SSE-strömmen
ska `result.motivering` visas som kursiv text under statusen (samma mönster som index.html).

Relevant rendering-mönster från index.html:
```javascript
${r.motivering ? `<div class="card-motivering" ...>${escHtml(r.motivering)}</div>` : ''}
```

**BYGGAGENTEN:** Använd samma CSS-klass `card-motivering` i chatboxens agentkortrendering.

---

### F3 — `questions`-respons från Promptsmeden: redan hanterat i index.html

Commit `f92c931` lade till stöd för `{type: "questions", ...}` från `/api/review` i index.html.
Chatboxen (SSE-strömmen) behöver också hantera detta fall — när `review_result.smith.type === "questions"`:

```
SSE-event: review_complete
payload.smith = {
  type: "questions",
  intro: "Beskriv X mer exakt...",
  questions: [
    { id: "q1", text: "Fråga?", options: ["Alt 1", "Alt 2", "Annat / vet ej"] }
  ]
}
```

**I chatboxen ska det renderas som:**
1. Visa Promptsmedens intro-text (förklaring)
2. Visa varje fråga med klickbara svarsalternativ
3. När användaren svarar: sammanställ svaren och lägg till dem i `idea_text` som en ny `/api/review`-körning
4. ALDRIG visa råa JSON-strukturen för barnanvändaren (KID_USER_PROMPT.md)

Barnanvändarens version: "Promptsmeden vill ställa några frågor innan den kan skriva instruktionen 🙋"

---

### F4 — `_SEVERITY_GUIDE` innehåller INTE `motivering` i JSON-schemat

Commit-meddelandet säger "Alla specialister maste motivera sin status" — men `_SEVERITY_GUIDE`
i app.py (~rad 1011) har INTE uppdaterats med `motivering` i JSON-schemat:

```python
# Nuläge (saknar motivering):
'{"status":"GODKÄND"|"UNDERKÄND","findings":[...],"severity":"...","suggestions":[...]}'
```

Konsekvens: agenter returnerar sällan `motivering` frivilligt — `card-motivering` visas sällan.
Fyndet är inte kritiskt för chatboxen, men är en inkonsistens att notera.

**Rekommendation (framtida fix):** Lägg till `motivering` i `_SEVERITY_GUIDE`:
```python
'{"status":"GODKÄND"|"UNDERKÄND","findings":[...],"severity":"...","suggestions":[...],"motivering":"en mening"}'
```

---

### Uppdaterad statusöversikt (E6 ersätts av detta)

| Komponent | Status |
|---|---|
| `byggs`→`kö` reset vid startup | ✅ Implementerat |
| `_ALWAYS_RUN_AGENT_IDS` | ✅ Implementerat |
| hemlighetsvakten hard-block | ✅ Implementerat |
| Sessionsnamn från `tolkad_ide` | ✅ Implementerat |
| `local_path` i settings (backend) | ✅ Implementerat |
| `_atomic_write()` | ✅ Implementerat |
| concurrency + krypto agenter | ✅ Implementerat |
| motivering-visning i agentkort | ✅ Implementerat (index.html) |
| questions-respons från Promptsmeden | ✅ Implementerat (index.html) |
| **index.html truncation — E1** | ❌ KRITISK — måste fixas |
| **AGENT_DISPLAY_NAMES saknar 7 agenter (F1)** | ❌ Saknas |
| **SSE endpoint `/api/builder/stream/{id}`** | ❌ Saknas (hela chatboxen) |
| **`#builderPanel` HTML + CSS + JS** | ❌ Saknas |
| `local_path` i inställnings-UI (index.html) | ❌ Saknas |
| `run_id` recovery-event i SSE (D2) | ❌ Saknas |
| `.gitignore` komplettering (D3) | ❌ Saknas |
| `_SEVERITY_GUIDE` saknar `motivering` (F4) | ⚠️ Inkonsistens |

---

## Iteration 5 — Fynd från ostaged working-tree-ändringar (2026-06-10)

Inga nya remote-pushs. Däremot finns tre filer med ostaged ändringar: `app.py`, `index.html`, `.gitignore`.

---

### G1 — `index.html` AVHUGGEN — BEKRÄFTAD (KRITISK BLOCKER)

`git diff index.html` visar att de sista 48 raderna saknas. Filen slutar abrupt på:

```
    updateActiveProjBadge(
```

**Förlorat innehåll (måste återställas):**
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

**Fix:** Append exakt ovanstående text till slutet av index.html.
**BLOCKERANDE** — utan denna fix är `DOMContentLoaded`-callbacken öppen och hela sidan är trasig.

---

### G2 — STOR ARKITEKTURÄNDRING: server-side projektinställningar (projects.json)

Working tree har lagt till komplett serverlagring av projektinställningar i `app.py`:

**Ny fil:** `projects.json` — `{ "<project_id>": { "disabled_agents": [...], "updated_at": "..." } }`

**Ny kod i app.py (~rad 2047–2088):**
```python
PROJECTS_FILE = BASE_DIR / "projects.json"
_projects_lock = threading.Lock()
_projects_load() → dict
_projects_write(data) → None   # atomisk
get_project_settings(project_id) → dict
save_project_settings(project_id, patch) → dict
```

**Tre nya API-endpoints:**
| Endpoint | Metod | Syfte |
|---|---|---|
| `/api/projects` | GET | Lista alla projekt med inställningar |
| `/api/projects/{id}/settings` | GET | Hämta inställningar + agentkataloget |
| `/api/projects/{id}/settings` | POST | Spara `disabled_agents`-lista |

**Viktig konsekvens för chatboxen:**
- Chatboxen kan nu hämta `disabled_agents` från servern via `GET /api/projects/{id}/settings`
- Chatboxen slipper skicka `disabled_agents` i varje review-request — servern slår ihop automatiskt
- ARKITEKTURANTAGANDET "server har ingen projektkännedom" gäller inte längre
- `projects.json` ska läggas till i `.gitignore` (innehåller lokal konfiguration)

---

### G3 — Ny agent: `agent_arkitektur` (Agentarkitekturagenten 🦾)

**Tillagd i SPECIALIST_AGENTS (~rad 1797) och i `_QUICK_AGENT_IDS`:**

```python
{
  "id": "agent_arkitektur",
  "name": "Agentarkitekturagenten",
  "emoji": "🦾",
  "phase": "post", "layer": "specialist",
  "modes": [M_NY, M_GRANSKA, M_BUGG],  # alla tre lägen
}
```

Kör i **snabbläge**. Kontrollerar: tool-sandboxing, path traversal i file-tools,
max-turns, resource cleanup, unbounded histories, prompt injection via tool-results,
privilegierade operationer, observability, rollback, kostnadstak.

**AGENT_DISPLAY_NAMES saknar nu totalt 10 agenter** (se uppdaterad lista nedan).

---

### G4 — Uppdaterat AGENT_DISPLAY_NAMES-krav (10 saknade agenter)

Tidigare angav spec 7 saknade agenter (F1). Nu är det 10:

```javascript
// Alla dessa saknas i AGENT_DISPLAY_NAMES i index.html (~rad 1357):
backend:          '⚙️ Backend-agenten',
devops:           '🚀 DevOps/CI-CD-agenten',
ai_ml:            '🤖 AI/ML-granskaren',
dokumentation:    '📖 Dokumentationsagenten',
licens:           '⚖️ Licensgranskaren',
i18n:             '🌍 i18n-agenten',
observability:    '📡 Observability-agenten',
concurrency:      '🧵 Trådsäkerhetsagenten',
krypto:           '🔐 Kryptoagenten',
agent_arkitektur: '🦾 Agentarkitekturagenten',
```

---

### G5 — `.gitignore` ostaged: `stop_app.bat` och `intrim_result*.json` borttagna

Working-tree-diff för `.gitignore` visar att `stop_app.bat` och `intrim_result*.json` tagits bort
ur ignore-listan. Dessutom läggs `projects.json` till. `.gitignore` saknar newline i slutet.

**Korrigerad `.gitignore` (komplett lista):**
```
__pycache__/
*.pyc
settings.json
sessions.json
backlog.json
build_queue.json
projects.json
build_results/
ai_eval_results.json
_blueprint.md
*.tmp
_final_design.md
_audit_plan.md
model_list_cache.json
.claude/settings.local.json
.env
start_background.vbs
stop_app.bat
intrim_result*.json
```

---

### G6 — UX-agenten: ny koll för teknisk jargong — direkt relevant för barnanvändaren

UX-agenten fick tre nya kontroller i working tree:
- `Målgruppsanpassning` — är UI-text anpassad för faktisk målgrupp (barn, seniorer)?
- `Teknisk jargong i UI` — används termer som 'stacktrace', 'commit', 'endpoint', 'query'?
- `alert()/confirm()` — används webbläsarens inbyggda popups?

Detta är direkt relaterat till `KID_USER_PROMPT.md` (primäranvändaren är 10 år).
Chatboxen ska ALDRIG visa tekniska termer utan filtrera dem via term-ersättningstabellen.

---

### G7 — Agent-mode-expansioner (INFO — påverkar inte chatboxen direkt)

| Agent | Förut | Nu |
|---|---|---|
| Hotmodelleraren | NY, BUGG | NY, GRANSKA, BUGG |
| Dataskyddsjuristen | NY, BUGG | NY, GRANSKA, BUGG |
| Riskvärderaren | NY | NY, GRANSKA |
| Frontend-agenten | NY, GRANSKA | NY, GRANSKA, BUGG |

Chatboxens SSE-rendering berörs inte — agents svarar med samma JSON-format oavsett mode.


---

# BYGGTASKLISTA — Alla uppgifter i exekveringsordning

> Varje task är designad att skickas separat till en byggagent.
> Skicka INTE nästa task förrän föregående är godkänd och mergad.
> PRINCIPREGEL: Systemet pushar ALDRIG automatiskt till git. Push är alltid en manuell användaråtgärd.

---

## TASK-T0 — Committa working tree innan bygge startar (MANUELL ANVÄNDARÅTGÄRD)

**Vem:** Användaren — inte byggagenten.
**Vad:** Nuvarande ostaged ändringar i `app.py`, `index.html`, `.gitignore` ska committas.
**Varför:** Byggagenten ska alltid jobba mot ren git-bas — annars vet inte granskningen vad som är nytt.

```bash
git add app.py index.html .gitignore
git commit -m "wip: agent-expansioner, projects.json-lagring, index.html-fix"
```

---

## TASK-T1 — Fixa index.html-trunkering (KRITISK BLOCKER)

**Fil:** `index.html`
**Prioritet:** KRITISK — sidan fungerar inte utan denna fix.

Sök efter raden som slutar med `updateActiveProjBadge(` (utan avslutande parentes).
Ersätt den med följande och lägg till allt som saknas efter:

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

**Verifiering:** `python -m py_compile app.py` bör inte klaga. Öppna sidan — om `DOMContentLoaded` körs korrekt syns projektväljarens innehåll och hälsocheck startar.

---

## TASK-T2 — Uppdatera AGENT_DISPLAY_NAMES i index.html

**Fil:** `index.html` (~rad 1357)
**Prioritet:** HÖG — settings-modal visar bara ID utan namn för 10 agenter.

Hitta `const AGENT_DISPLAY_NAMES = {` och lägg till dessa rader inuti objektet:

```javascript
  backend:          '⚙️ Backend-agenten',
  devops:           '🚀 DevOps/CI-CD-agenten',
  ai_ml:            '🤖 AI/ML-granskaren',
  dokumentation:    '📖 Dokumentationsagenten',
  licens:           '⚖️ Licensgranskaren',
  i18n:             '🌍 i18n-agenten',
  observability:    '📡 Observability-agenten',
  concurrency:      '🧵 Trådsäkerhetsagenten',
  krypto:           '🔐 Kryptoagenten',
  agent_arkitektur: '🦾 Agentarkitekturagenten',
```

**Verifiering:** Öppna Settings → Agent-modeller. Alla agenter ska visa namn + emoji, inte bara ID.

---

## TASK-T3 — Fixa .gitignore

**Fil:** `.gitignore`
**Prioritet:** MEDEL — förhindrar oavsiktlig commit av lokala datafiler.

Ersätt hela filinnehållet med:

```
__pycache__/
*.pyc
settings.json
sessions.json
backlog.json
build_queue.json
projects.json
build_results/
ai_eval_results.json
_blueprint.md
*.tmp
_final_design.md
_audit_plan.md
model_list_cache.json
.claude/settings.local.json
.env
start_background.vbs
stop_app.bat
intrim_result*.json
```

**Verifiering:** `git status` ska inte lista `projects.json`, `stop_app.bat` eller `intrim_result*.json` som untracked.

---

## TASK-T4 — Lägg till `local_path` i settings-modal (index.html)

**Fil:** `index.html`
**Prioritet:** MEDEL — `local_path` sparas redan av backend men saknar UI-fält.
**Beroende:** T1 ska vara mergad.

Hitta settings-modalen i `openSettings()` / `saveSettings()`. Lägg till ett textfält:

```html
<div class="settings-row">
  <label>Lokal projektmapp</label>
  <input type="text" id="localPathInput"
         placeholder="/hem/mig/mitt-projekt"
         style="font-family:monospace; width:100%">
  <small style="color:var(--text3)">Byggagentens rotkatalog på denna dator</small>
</div>
```

I `openSettings()` — läs värdet:
```javascript
document.getElementById('localPathInput').value = s.local_path || '';
```

I `saveSettings()` — spara värdet:
```javascript
local_path: document.getElementById('localPathInput').value.trim(),
```

**Verifiering:** Spara ett värde i fältet → `GET /api/settings` ska returnera `local_path` med rätt värde.

---

## TASK-T5 — Bygg SSE-endpoint `/api/builder/stream/{item_id}` (app.py)

**Fil:** `app.py`
**Prioritet:** HÖG — kärnan i chatboxen. Allt T6-T8 beror på detta.
**Beroende:** T0.

Lägg till efter de befintliga build_queue-endpoints (~rad 500). Spec-referens: avsnitt "2. SSE endpoint" ovan.

**Översikt:**
1. Validera `item_id` — `404` om ej finns i kön
2. Skicka `init`-event med item-data
3. Kör agent-loopen (Anthropic AsyncAnthropic med tool-use)
4. Streama varje `tool_call`, `tool_result`, `text_delta`, `agent_done`, `review_start`, `review_complete`
5. Vid Promptsmeden `type=questions` → skicka `review_complete` med `smith.type="questions"` och frågorna
6. Vid klart: committa lokalt (ALDRIG push), skicka `ready_to_push`-event
7. Avbryt-stöd via `asyncio.Event` och `GET /api/builder/cancel/{item_id}`

**Keepalive-pattern (undviker proxy-timeout):**
```python
async def keepalive():
    while not done_event.is_set():
        await asyncio.sleep(15)
        yield f"event: keepalive\ndata: {{}}\n\n"
```

**PRINCIPREGEL:** Agenten committar lokalt, skickar `ready_to_push`. Push sker ALDRIG automatiskt.

**Verifiering:** `curl -N http://localhost:8001/api/builder/stream/<id>` ska streama events.

---

## TASK-T6 — Bygg chatbox-panelen `#builderPanel` i index.html

**Fil:** `index.html`
**Prioritet:** HÖG — användarens primära yta.
**Beroende:** T1, T5.

**HTML-struktur** (lägg till i `<body>`):
```html
<div id="builderPanel" class="builder-panel" aria-label="Byggare" hidden>
  <div class="builder-header">
    <span id="builderTitle">🏗️ Byggare</span>
    <button onclick="closeBuilderPanel()" aria-label="Stäng">✕</button>
  </div>
  <div id="builderMessages" class="builder-messages"></div>
  <div id="builderStatus" class="builder-status"></div>
  <div id="builderActions" class="builder-actions" hidden></div>
</div>
```

**Funktioner att implementera:**
- `openBuilderPanel(itemId)` — ersätter `startBuild()`, öppnar panel + startar SSE
- `closeBuilderPanel()` — stänger panel, avbryter SSE-anslutning
- `_connectBuilderSSE(itemId)` — EventSource mot `/api/builder/stream/{itemId}`
- `_handleBuilderEvent(type, data)` — router för alla event-typer
- `_renderToolCall(data)` — visar "🔧 Agenten tittar på..." (aldrig råa tool-calls)
- `_renderReviewResult(data)` — renderar agentkortar med status + motivering
- `_renderQuestionsForm(data)` — renderar Promptsmedens frågor som klickbara knappar
- `_renderReadyToPush(data)` — visar push-knapp och commit-meddelande

**Barnanvändarens termer** (ersättningstabellen från KID_USER_PROMPT.md):
```javascript
const KID_TERMS = {
  'commit':    'sparar',
  'push':      'skickar',
  'git':       '',          // ta bort ordet helt
  'endpoint':  '',
  'SSE':       '',
  'stderr':    '',
  'byggs':     'håller på att byggas ⏳',
  'klar':      'Klart! ✅',
  'behover_dig': 'Behöver din hjälp 🙋',
};
```

**Verifiering:** Klicka "Bygg" på ett köat ärende → panelen öppnas, meddelanden strömmar in med barnvänliga termer.

---

## TASK-T7 — Koppla "Bygg"-knappen till `openBuilderPanel()`

**Fil:** `index.html`
**Prioritet:** MEDEL
**Beroende:** T6.

Hitta `startBuild()` och `renderQueueBox()`. Ändra:
- `byggs`-kortets "Kontrollera"-knapp → anropar `openBuilderPanel(item.id)` istället för clipboard
- `kö`-kortets "Bygg"-knapp (om den finns) → same

Ta bort alla `navigator.clipboard`-anrop i byggarflödet.

**Verifiering:** Klicka knappen — ingen clipboard-dialog, panelen öppnas direkt.

---

## TASK-T8 — Hantera `questions`-respons i chatbox

**Fil:** `index.html`
**Prioritet:** MEDEL
**Beroende:** T6.

När `_handleBuilderEvent('review_complete', data)` körs och `data.smith.type === 'questions'`:

```javascript
function _renderQuestionsForm(smith) {
  const el = document.createElement('div');
  el.className = 'builder-questions';
  el.innerHTML = `
    <p class="questions-intro">${escHtml(smith.intro)}</p>
    ${smith.questions.map(q => `
      <div class="question-block">
        <p>${escHtml(q.text)}</p>
        <div class="options">
          ${q.options.map(o =>
            `<button class="option-btn" onclick="_answerQuestion('${q.id}','${escHtml(o)}')">${escHtml(o)}</button>`
          ).join('')}
        </div>
      </div>
    `).join('')}
  `;
  document.getElementById('builderMessages').appendChild(el);
}
```

`_answerQuestion(qId, answer)` samlar svar och skickar ny `/api/review` med svaren inbakade i `idea_text`.

**Barnvänlig rubrik:** "Promptsmeden vill ställa några frågor 🙋"

**Verifiering:** Skicka in ett vagt ärende → chatboxen visar frågor som klickbara knappar, inte rå JSON.

---

## TASK-T9 — Lägg till `motivering` i `_SEVERITY_GUIDE` (app.py)

**Fil:** `app.py` (~rad 1011)
**Prioritet:** LÅG — förbättring, inte blockerande.

Hitta `_SEVERITY_GUIDE`-strängen och lägg till `"motivering"` i JSON-schemat:

```python
_SEVERITY_GUIDE = (
    " Severity: HIGH=kritisk/måste åtgärdas, MEDIUM=bör åtgärdas, LOW=rekommendation."
    " Severity sätts efter ditt ALLVARLIGASTE fynd — inte genomsnittet."
    " En enda bekräftad injection, trasig auth eller exponerad hemlighet ⇒ HIGH."
    " Om inga verkliga problem hittas: returnera status GODKÄND med tomma listor."
    " Returnera ENBART JSON: "
    '{"status":"GODKÄND"|"UNDERKÄND","findings":["konkret problem..."],'
    '"severity":"LOW"|"MEDIUM"|"HIGH","suggestions":["åtgärd..."],'
    '"motivering":"en mening om varför denna status"}'
)
```

**Verifiering:** Kör en review → agentkortar visar `motivering` regelbundet.

---

## Turordning och beroenden

```
T0 (manuell) → T1 → T2, T3, T4 (parallella) → T5 → T6 → T7, T8 (parallella) → T9
```

| Task | Beroer på | Blockerande |
|---|---|---|
| T0 | — | Ja — alla T* beror på ren git-bas |
| T1 | T0 | Ja — sidan är trasig utan denna |
| T2 | T1 | Nej |
| T3 | — | Nej |
| T4 | T1 | Nej |
| T5 | T0 | Ja — T6–T8 beror på SSE-endpoint |
| T6 | T1, T5 | Ja — T7, T8 beror på panelen |
| T7 | T6 | Nej |
| T8 | T6 | Nej |
| T9 | — | Nej |


---

## Iteration 8 — Fynd från remote-granskning och divergerade branches (2026-06-10)

*Källmaterial: git fetch origin + diff mot origin/main + app.py (lokal working tree)*

---

### G1 — BRANCHES DIVERGERADE (ÅTGÄRD KRÄVS INNAN PUSH)

Lokal branch och `origin/main` delar common ancestor `1c6bc3d` men har sedan divergerat:

**Lokalt (ej på origin):** 8 commits — nya agenter (concurrency, krypto m.fl.), C1–C5-fixes, modifieringar i SPECIALIST_AGENTS
**Origin (ej lokalt):** Merge-commit `3654bd7` — PR #2 `feat/agent-audit-export` med:
- `MAX_INPUT` 80k → 450k, `MAX_TOTAL_CHARS` 60k → 400k, `MAX_FILE_CHARS` 8k → 200k
- Vag buggrapport-gate (kräver >=20 tecken / >=3 ord i FELBESKRIVNING)
- `_stash_run_result()` + `/api/review/result/{run_id}` för reconnect vid timeout
- `exclude_paths` i GitHub-fetch (hindrar eval-fixturer från att ge falska fynd)
- Bättre timeouts: HTTP 80→110s, specialist 95→130s, gather 200→320s
- Trådpool 40→80 workers ✅ (lokal har redan 80)
- `supabase_setup.sql` utökad med schema-migrationsledger

**Rekommenderad åtgärd:** `git rebase origin/main` (eller merge) — se till att C1–C5 fixarna
(startup reset, reload=False, _ALWAYS_RUN_AGENT_IDS etc.) inte tappas i processen.

---

### G2 — `reload=True` kvar i origin/main

`origin/main:app.py` sista rad: `uvicorn.run(..., reload=True)`.
C2-fixet (reload=False) finns BARA i lokalt working tree.
**Vid rebase/merge måste `reload=False` behållas.**

---

### AO — `_progress`-GC triggar bara vid aktiva skrivningar (minnesläcka vid krasch)

```python
# app.py — _progress_set()
cutoff = entry["updated"] - 900          # 15 min bak i tid
for k in [k for k, v in _progress.items() if v.get("updated", 0) < cutoff]:
    _progress.pop(k, None)
```

GC körs INUTI `_progress_set()` — dvs. bara när en ny progress-uppdatering inkommer.
Om en run kraschar mitt i (exception i en agent, server-restart under en körning)
kallas aldrig `_progress_set` med `phase="klar"`, och entry stannar tills en
*annan* körnings GC-svep råkar täcka timestamps.

**Samma mönster gäller `_RUN_RESULTS`** — GC körs bara i `_stash_run_result()`.

**Fix:** Lägg till en bakgrundsuppgift i `startup()` som rensar gamla entries periodiskt:
```python
@app.on_event("startup")
async def startup():
    _migrate_sessions()
    # ... befintlig byggs-reset ...
    asyncio.get_event_loop().create_task(_gc_loop())

async def _gc_loop():
    """Rensa _progress och _RUN_RESULTS var 5:e minut oavsett aktivitet."""
    while True:
        await asyncio.sleep(300)
        cutoff = datetime.now().timestamp() - 900
        with _progress_lock:
            for k in [k for k, v in _progress.items() if v.get("updated", 0) < cutoff]:
                _progress.pop(k, None)
        with _run_results_lock:
            for k in [k for k, v in _RUN_RESULTS.items() if now - v["ts"] > 1800]:
                del _RUN_RESULTS[k]
```

---

### AP — Bilder saknar byte-storleksgräns

```python
images = [i for i in images if isinstance(i, str) and i.startswith("data:image")][:6]
```

Antalet bilder är cappat till 6 men ingen gräns per bild eller totalt.
En 4K-skärmdump som PNG är ~5–15 MB base64 — sex sådana = 90 MB i ett enda API-anrop.
OpenRouter-klienten får ett enormt payload → timeout eller OOM.

**Fix:** Lägg till byte-gräns efter listfiltrering:
```python
MAX_IMAGE_BYTES = 8_000_000   # 8 MB per bild (base64 ≈ 133 % av råfil)
MAX_TOTAL_IMAGE_BYTES = 20_000_000  # 20 MB totalt
images = [i for i in images
          if isinstance(i, str) and i.startswith("data:image")
          and len(i) <= MAX_IMAGE_BYTES][:6]
if sum(len(i) for i in images) > MAX_TOTAL_IMAGE_BYTES:
    images = []   # hellre inga bilder än en jättepayload
```

---

### AR — `.gitignore` saknar lokala arbets- och analysfilar

Följande filer är untracked (`git status --short` visar `??`) men saknas i `.gitignore`:

| Fil | Varför ska den ignoreras |
|---|---|
| `AGENT_CHATBOX_BUILD.md` | Intern specifikation, inte produktionskod |
| `ARKITEKTUR_ANALYS.md` | Analysresultat från agenter |
| `CODEBASE_AUDIT.md` | Analysresultat från agenter |
| `KID_USER_PROMPT.md` | Intern UX-spec |
| `intrim_result.json` | Temporärt testresultat |
| `intrim_result_concrete.json` | Temporärt testresultat |
| `test_intrim.py` | Temporärt testskript |

Remote (origin/main) har `stop_app.bat` i `.gitignore` men lokal har det inte — synkronisera.

**Fix i `.gitignore`:**
```
# Interna specs och analysresultat
AGENT_CHATBOX_BUILD.md
ARKITEKTUR_ANALYS.md
CODEBASE_AUDIT.md
KID_USER_PROMPT.md
stop_app.bat
# Temporära testfiler
intrim_result*.json
test_intrim.py
```

---

### AS — `run_id`-sökvägsparameter saknar längdvalidering

POST-body capar `run_id` till 64 tecken:
```python
run_id = str(payload.get("run_id", ""))[:64]
```

Men path-parametrarna i GET-endpoints capar inte:
```python
@app.get("/api/review/result/{run_id}")   # run_id kan vara godtyckligt lång
@app.get("/api/progress/{run_id}")         # samma
```

Konsekvens: en klient kan skicka en URL med 100 kB lång `run_id` — no direct RCE
men det loggas i uvicorn-accessloggar och kastar en onödigt stor dict-nyckel.

**Fix:** Validera format i endpoint-kroppen:
```python
@app.get("/api/review/result/{run_id}")
async def get_review_result(run_id: str):
    if len(run_id) > 64 or not run_id.replace("-", "").isalnum():
        return JSONResponse({"ready": False}, status_code=404)
    ...
```

---

### Uppdaterad prioriteringslista (alla iterationer sammanlagda)

| Prio | ID | Titel | Var |
|---|---|---|---|
| 🔴 P0 | G1 | Rebase/merge mot origin/main | Git |
| 🔴 P0 | E1 | `index.html` avhuggen (återställ slutet) | index.html |
| 🟠 P1 | AR | `.gitignore` komplettering | .gitignore |
| 🟠 P1 | G2 | `reload=False` bevaras vid merge | app.py |
| 🟠 P1 | AO | GC-loop för `_progress` och `_RUN_RESULTS` | app.py |
| 🟡 P2 | AP | Byte-gräns för bilder | app.py |
| 🟡 P2 | AS | `run_id` path-param validering | app.py |
| 🟡 P2 | AM | `project_context` sparas i queue-item | app.py |
| 🟡 P2 | AL | `auto_advance`/`builder_review_depth` i inställnings-UI | index.html |
| 🟡 P2 | F1 | `AGENT_DISPLAY_NAMES` saknar 7+2 agenter | index.html |
| 🔵 P3 | F4 | `_SEVERITY_GUIDE` saknar `motivering`-fält | app.py |
| 🔵 P3 | Chatbox | SSE-endpoint + `#builderPanel` | app.py + index.html |

---

## BYGGPLAN — Fristående tasks för byggagenten

*Varje task nedan är komplett och kan skickas separat till en byggagent.*
*Format: Titel · Fil · Vad · Acceptanskriterium*

---

### TASK-01 · `.gitignore` komplettering

**Fil:** `.gitignore`

**Bakgrund:** Flera lokala arbets- och analysfilar är untracked och riskerar att commitas av misstag.

**Vad du ska göra:**
Öppna `.gitignore` och lägg till följande rader (om de inte redan finns):
```
# Interna specs och analysresultat
AGENT_CHATBOX_BUILD.md
ARKITEKTUR_ANALYS.md
CODEBASE_AUDIT.md
KID_USER_PROMPT.md
stop_app.bat
# Temporära testfiler
intrim_result*.json
test_intrim.py
projects.json
```

**Acceptanskriterium:**
- `git status --short` visar INTE `?? AGENT_CHATBOX_BUILD.md` eller `?? intrim_result.json`
- `.gitignore` innehåller alla rader ovan
- Befintliga rader ändras INTE

---

### TASK-02 · Periodisk GC för `_progress` och `_RUN_RESULTS`

**Fil:** `app.py`

**Bakgrund:** `_progress` och `_RUN_RESULTS` rensas bara när nya skrivningar sker.
En kraschad körning lämnar entries som aldrig ålkas ut.

**Vad du ska göra:**

1. Hitta `startup()`-funktionen (sök: `async def startup`).

2. Lägg till en task-skapning sist i `startup()`:
```python
    asyncio.get_event_loop().create_task(_memory_gc_loop())
```

3. Lägg till följande funktion OVANFÖR `startup()`:
```python
async def _memory_gc_loop():
    """Rensa in-memory stores var 5:e minut oavsett aktivitet.
    Utan detta lever kraschade körningars entries tills nästa write-GC."""
    import asyncio as _asyncio
    while True:
        await _asyncio.sleep(300)
        now = datetime.now().timestamp()
        with _progress_lock:
            stale = [k for k, v in _progress.items() if v.get("updated", 0) < now - 900]
            for k in stale:
                _progress.pop(k, None)
        with _run_results_lock:
            stale2 = [k for k, v in _RUN_RESULTS.items() if now - v["ts"] > 1800]
            for k in stale2:
                del _RUN_RESULTS[k]
```

**Acceptanskriterium:**
- `python -c "import ast; ast.parse(open('app.py').read()); print('OK')"` returnerar `OK`
- Funktionen `_memory_gc_loop` finns i filen
- `create_task(_memory_gc_loop())` anropas i `startup()`

---

### TASK-03 · Byte-storleksgräns för bilder i `/api/review`

**Fil:** `app.py`

**Bakgrund:** Bilder cappas till 6 stycken men ingen storleksgräns per bild.
En enda 4K-PNG är ~10 MB base64 — sex sådana ger ett 60 MB API-anrop.

**Vad du ska göra:**

Hitta raden (sök: `images = [i for i in images if isinstance(i, str) and i.startswith("data:image")]`).

Ersätt den med:
```python
MAX_IMAGE_BYTES = 8_000_000        # 8 MB per bild (base64 ≈ 133% av råfil → ~6 MB original)
MAX_TOTAL_IMAGE_BYTES = 20_000_000 # 20 MB totalt för hela anropet
images = [i for i in images
          if isinstance(i, str) and i.startswith("data:image")
          and len(i) <= MAX_IMAGE_BYTES][:6]
if sum(len(i) for i in images) > MAX_TOTAL_IMAGE_BYTES:
    images = []   # hellre inga bilder än OOM/timeout
```

**Acceptanskriterium:**
- `MAX_IMAGE_BYTES` och `MAX_TOTAL_IMAGE_BYTES` finns i filen
- `python -c "import ast; ast.parse(open('app.py').read()); print('OK')"` returnerar `OK`

---

### TASK-04 · Validera `run_id` i GET-endpoints

**Fil:** `app.py`

**Bakgrund:** POST-body capar `run_id` till 64 tecken men GET path-params gör det inte.

**Vad du ska göra:**

1. Hitta `async def get_review_result(run_id: str):` och lägg till validering som FÖRSTA sats i kroppen:
```python
    if len(run_id) > 64 or not all(c in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in run_id.lower()):
        return JSONResponse({"ready": False}, status_code=404)
```

2. Hitta `async def get_progress(run_id: str):` och lägg till samma validering som FÖRSTA sats:
```python
    if len(run_id) > 64 or not all(c in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in run_id.lower()):
        return {"phase": "okänd", "agents": {}}
```

**Acceptanskriterium:**
- Båda endpoints har längdvalidering
- `python -c "import ast; ast.parse(open('app.py').read()); print('OK')"` returnerar `OK`

---

### TASK-05 · `project_context` sparas i queue-item vid `/send`

**Fil:** `app.py`

**Bakgrund:** `/send` bygger `project_context` från `profile` men sparar det inte i queue-item.
Vid omförsök eller reconnect med ändrade inställningar får byggaren fel kontext.

**Vad du ska göra:**

1. Hitta `job`-dict i `send_build_queue_item()` (sök: `"project_context": build_project_context(profile)`).

2. Spara `project_context` till `item` INNAN `_queue_write(items)` i send-blocket:
```python
        item["project_context_snapshot"] = build_project_context(profile)
```

3. Använd den sparade snapshoten i `job`-dict:
```python
        "project_context": item.get("project_context_snapshot", build_project_context(profile)),
```

**Acceptanskriterium:**
- `project_context_snapshot` sparas i queue-item (kan verifieras i `build_queue.json` efter ett `/send`-anrop)
- `python -c "import ast; ast.parse(open('app.py').read()); print('OK')"` returnerar `OK`

---

### TASK-06 · `AGENT_DISPLAY_NAMES` kompletteras med 9 saknade agenter

**Fil:** `index.html`

**Bakgrund:** Inställnings-modalen visar bara agent-ID (utan emoji/namn) för nya agenter.

**Vad du ska göra:**

Hitta `AGENT_DISPLAY_NAMES` i `index.html` (sök: `const AGENT_DISPLAY_NAMES`).
Lägg till dessa nycklar i objektet (om de saknas — sök INNAN du skriver):
```javascript
"backend":       "⚙️ Backend-agenten",
"devops":        "🚀 DevOps/CI-CD-agenten",
"ai_ml":         "🤖 AI/ML-granskaren",
"dokumentation": "📖 Dokumentationsagenten",
"licens":        "⚖️ Licensgranskaren",
"i18n":          "🌍 i18n-agenten",
"observability": "📡 Observability-agenten",
"concurrency":   "🧵 Trådsäkerhetsagenten",
"krypto":        "🔐 Kryptoagenten",
```

**Acceptanskriterium:**
- Alla 9 nycklar finns i `AGENT_DISPLAY_NAMES`
- Inget befintligt värde ändras
- Sidan laddar utan JS-fel (kontrollera browser console)

---

### TASK-07 · `_SEVERITY_GUIDE` får `motivering`-fält

**Fil:** `app.py`

**Bakgrund:** `_SEVERITY_GUIDE` definierar JSON-schemat som alla specialistagenter ska returnera.
Fältet `motivering` är sedan länge visat i UI:n (card-motivering) men saknas i schemat.
Agenter returnerar det sällan frivilligt eftersom det inte finns i instruktionen.

**Vad du ska göra:**

Hitta `_SEVERITY_GUIDE` (sök: `_SEVERITY_GUIDE = `).
Lägg till `"motivering"` i JSON-schemat:
```python
# Innan (schema-raden):
'{"status":"GODKÄND"|"UNDERKÄND","findings":[...],"severity":"...","suggestions":[...]}'

# Efter:
'{"status":"GODKÄND"|"UNDERKÄND","findings":[...],"severity":"...","suggestions":[...],"motivering":"en mening på svenska som förklarar statusen"}'
```

Uppdatera också instruktionen som beskriver `motivering` till att säga att det är OBLIGATORISKT.

**Acceptanskriterium:**
- `"motivering"` finns i `_SEVERITY_GUIDE`-strängen
- `python -c "import ast; ast.parse(open('app.py').read()); print('OK')"` returnerar `OK`

---

### TASK-08 · Chatbox — SSE-endpoint i `app.py`

**Fil:** `app.py`

**Bakgrund:** Chatboxen (buildarens kommunikationskanal direkt i UI:n) kräver
en SSE-endpoint som strömmar byggagentens output i realtid.

**Vad du ska göra:**

Lägg till följande endpoint i `app.py` (efter de befintliga build-queue-endpointsen):

```python
from fastapi.responses import StreamingResponse

@app.get("/api/builder/stream/{item_id}")
async def builder_stream(item_id: str):
    """SSE-ström för byggagentens realtidsoutput.
    Klienten lyssnar med EventSource('/api/builder/stream/{item_id}').
    
    Events:
      builder_log    — { message: str }          löpande statusmeddelanden
      builder_done   — { status: "klar"|"fel", summary: str }
      heartbeat      — {} (var 15:e sekund för att hålla kopplingen levande)
    """
    if len(item_id) > 64:
        return JSONResponse({"error": "Ogiltigt item_id"}, status_code=400)

    async def event_stream():
        import json, asyncio
        # Heartbeat så att proxy/browser inte stänger kopplingen
        while True:
            yield f"event: heartbeat\ndata: {{}}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # nginx: stäng av buffering
        },
    )
```

**OBS:** Detta är ett skelett — byggaren kopplar in faktisk agentstyrning i en senare task.

**Acceptanskriterium:**
- `GET /api/builder/stream/{item_id}` returnerar `text/event-stream`
- Skickar `heartbeat`-events var 15:e sekund
- `python -c "import ast; ast.parse(open('app.py').read()); print('OK')"` returnerar `OK`

---

### TASK-09 · Chatbox — `#builderPanel` i `index.html`

**Fil:** `index.html`

**Bakgrund:** Chatboxen ska visas som en panel i "Att bygga"-fliken när ett ärende är aktivt.

**Vad du ska göra:**

Lägg till följande HTML i `Att bygga`-fliken, direkt under knapp-raden för `byggs`-items:

```html
<!-- Byggchatbox — visas när ett ärende är i status "byggs" -->
<div id="builderPanel" class="builder-panel" style="display:none">
  <div class="builder-panel-header">
    <span>🤖 Byggagenten</span>
    <button onclick="closeBuilderPanel()" class="btn-icon" title="Stäng">✕</button>
  </div>
  <div id="builderLog" class="builder-log"></div>
  <div class="builder-input-row">
    <input id="builderInput" type="text" placeholder="Skriv till byggagenten..." 
           onkeydown="if(event.key==='Enter') sendBuilderMessage()">
    <button onclick="sendBuilderMessage()" class="btn-primary">Skicka</button>
  </div>
</div>
```

Lägg till CSS (i `<style>`-blocket):
```css
.builder-panel { border: 1px solid var(--border); border-radius: 8px; margin-top: 12px; }
.builder-panel-header { padding: 8px 12px; background: var(--surface2); display: flex; justify-content: space-between; align-items: center; font-weight: 600; border-radius: 8px 8px 0 0; }
.builder-log { height: 220px; overflow-y: auto; padding: 10px 12px; font-family: monospace; font-size: 12px; white-space: pre-wrap; background: var(--bg); }
.builder-input-row { display: flex; gap: 6px; padding: 8px 12px; border-top: 1px solid var(--border); }
.builder-input-row input { flex: 1; }
```

Lägg till JS (i `<script>`-blocket):
```javascript
let _builderSource = null;

function openBuilderPanel(itemId) {
  document.getElementById('builderPanel').style.display = 'block';
  const log = document.getElementById('builderLog');
  log.textContent = '';
  if (_builderSource) _builderSource.close();
  _builderSource = new EventSource(`/api/builder/stream/${itemId}`);
  _builderSource.addEventListener('builder_log', e => {
    const d = JSON.parse(e.data);
    log.textContent += d.message + '\n';
    log.scrollTop = log.scrollHeight;
  });
  _builderSource.addEventListener('builder_done', e => {
    const d = JSON.parse(e.data);
    log.textContent += `\n✅ ${d.summary}\n`;
    log.scrollTop = log.scrollHeight;
  });
}

function closeBuilderPanel() {
  if (_builderSource) { _builderSource.close(); _builderSource = null; }
  document.getElementById('builderPanel').style.display = 'none';
}

function sendBuilderMessage() {
  const inp = document.getElementById('builderInput');
  const msg = inp.value.trim();
  if (!msg) return;
  inp.value = '';
  // TODO: POST till /api/builder/message när endpointen finns
  const log = document.getElementById('builderLog');
  log.textContent += `Du: ${msg}\n`;
  log.scrollTop = log.scrollHeight;
}
```

**Acceptanskriterium:**
- `#builderPanel` finns i DOM
- `openBuilderPanel(itemId)` öppnar panelen och kopplar EventSource
- Panelen stängs med ✕-knappen
- Sidan laddar utan JS-fel (kontrollera browser console)

