# BYGG_TASKS — Prioriterad uppgiftslista för byggaren

> **Hur du använder den här filen:**
> Skicka EN uppgift i taget till byggaren. Varje uppgift är självständig och kan köras isolerat.
> Ordningen nedan är beroendekedjad — gör T1 → T2 → T3 → T4a → T4b → T4 → T5 → T6 → T7 → T8 → T9 → T11 → T12.
> Bakgrundsinformation och detaljanalys finns i `AGENT_CHATBOX_BUILD.md`.
>
> **Senast uppdaterad:** 2026-06-10, Iteration 8

---

## STATUSÖVERSIKT — RÄTT ORDNING

| ID | Uppgift | Prioritet | Est. | Status | Beroende av |
|---|---|---|---|---|---|
| T1 | Fixa index.html-truncation | 🔴 AKUT | 10 min | ❌ Ej gjord | — |
| T2 | Fixa switchView() wipes builder-active | 🔴 BLOKERANDE | 5 min | ❌ Ej gjord | T1 |
| T3 | Komplettera .gitignore | 🟡 | 5 min | ❌ Ej gjord | — |
| T4a | Backend: lägg till "builder" i _DEFAULT_AGENT_MODELS | 🔴 KÄRNA | 5 min | ❌ Ej gjord | — |
| T4b | Backend: project_context_snapshot sparas vid /send | 🔴 KÄRNA | 20 min | ❌ Ej gjord | — |
| T4 | Backend: SSE-endpoint + BUILDER_TOOLS + agentic loop | 🔴 KÄRNA | 4–6h | ❌ Ej gjord | T4a, T4b |
| T5 | Frontend: #builderPanel HTML + CSS | 🟡 | 1h | ❌ Ej gjord | T1 |
| T6 | Frontend: builder JS — openBuilderPanel + SSE + meddelanden | 🟡 | 2h | ❌ Ej gjord | T4, T5 |
| T7 | Frontend: ersätt startBuild clipboard med openBuilderPanel | 🟡 | 30 min | ❌ Ej gjord | T6 |
| T8 | Frontend: renderQueueBox — barnvänliga knappar + data-item-id | 🟡 | 30 min | ❌ Ej gjord | T6 |
| T9 | Settings UI: lägg till local_path-fält | 🟡 | 30 min | ❌ Ej gjord | T1 |
| T11 | Frontend: AGENT_DISPLAY_NAMES — komplettera alla agenter | 🟢 | 15 min | ❌ Ej gjord | — |
| T12 | Frontend: Reconnect-knapp vid page refresh | 🟢 | 30 min | ❌ Ej gjord | T8 |

---

## ⚠️ KÄNDA FALLGROPAR — läs innan du börjar

### F1 — Modellsträngsformat (KRITISK i T4)
`_DEFAULT_AGENT_MODELS` använder OpenRouter-format: `"anthropic/claude-sonnet-4.6"` (snedstreck, punkt).
`anthropic.AsyncAnthropic` kräver Anthropic native-format: `"claude-sonnet-4-6"` (inga prefix, bindestreck).

**Normalisera alltid** modellsträngen i T4:
```python
def _normalize_anthropic_model(m: str) -> str:
    m = m.strip().removeprefix("anthropic/")
    return m.replace(".", "-")
# Exempel: "anthropic/claude-sonnet-4.6" → "claude-sonnet-4-6"
```

### F2 — `project_context_snapshot` är None tills T4b är gjord
T4:s SSE-endpoint läser `item.get("project_context_snapshot")` från `build_queue.json`.
Utan T4b sparas aldrig detta fält — fallback är `item.get("spec_markdown", "")` vilket fungerar men ger sämre kontext till agenten. Gör T4b FÖRE T4.

### F3 — `data-item-id` saknas på queue-korten
T12 behöver hitta ett specifikt kort med `querySelector('[data-item-id="..."]')`.
Attributet finns inte på korten idag. Lägg till det i T8 (renderQueueBox).

### F4 — `github_fetch()` returnerar JSONResponse vid fel
I T4:s auto-granskningssteg: `await github_fetch({...})` kan returnera `JSONResponse` (inte dict) om repot saknas. Kontrollera typen:
```python
code_resp = await github_fetch({...})
if isinstance(code_resp, JSONResponse):
    yield _sse({"type": "warning", "text": "Kunde inte hämta kod från GitHub — kontrollera repo/branch i projektet."})
else:
    code = code_resp.get("code", "") if isinstance(code_resp, dict) else ""
```

---

## T1 — Fixa index.html-truncation

**Prioritet: 🔴 AKUT — appen startar inte förrän detta är fixat**

**Vad som är fel:**
`index.html` slutar på rad 4076 med `updateActiveProjBadge(` utan avslutande parentes.
JS-parsern kastar `SyntaxError: Unexpected end of input` → sidan är vit.

**Var i filen:** Rad 4076 — slutet av filen.

**Exakt vad som ska läggas till i slutet** (klistra in direkt efter `updateActiveProjBadge(`):

```javascript
);
    loadHistory();          // load AFTER project is set so filter is correct
    updateGithubSection();  // setup github row based on active project
    refreshByggaBadge();    // tab badge + attention banner
  });
  setTimeout(() => runHealthCheck(), 800);
});

document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    // Respect the disabled run button — otherwise concurrent reviews race
    if (!document.getElementById('runBtn').disabled) runReview();
  }
});

// Paste screenshots from clipboard (code/bug modes)
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

**Verifiera:** Öppna http://localhost:8001 — sidan ska laddas utan vit skärm.

---

## T2 — Fixa switchView() wipes builder-active

**Prioritet: 🔴 BLOKERANDE — utan detta försvinner byggpanelen vid navigering**

**Var i filen:** `index.html`, sök efter `function switchView` (~rad 1958).

**Vad som är fel:**
```javascript
// FEL — skriver över ALLA body-klasser inkl. builder-active:
document.body.className = 'view-' + name;
```

**Ersätt med:**
```javascript
function switchView(name) {
  // Ta bort alla view-klasser men BEHÅLL builder-active och andra custom-klasser
  document.body.classList.remove('view-bestall', 'view-bygga', 'view-historik');
  document.body.classList.add('view-' + name);
  // ... resten av funktionen oförändrad
}
```

**Verifiera:** Öppna byggpanelen → navigera till en annan vy → navigera tillbaka → panelen ska fortfarande synas.

---

## T3 — Komplettera .gitignore

**Prioritet: 🟡 — förhindrar att testfiler och intern dokumentation commitas**

**Var i filen:** `.gitignore` i roten.

**Lägg till i slutet** (kontrollera att raderna inte redan finns innan du lägger till):

```
# Test- och eval-artefakter
intrim_result_concrete.json
test_intrim.py

# Intern dokumentation (ska ej vara i main)
ARKITEKTUR_ANALYS.md
KID_USER_PROMPT.md
AGENT_CHATBOX_BUILD.md
BYGG_TASKS.md
```

**Verifiera:** `git status` ska inte längre visa dessa filer som untracked.

---

## T4a — Backend: lägg till "builder" i _DEFAULT_AGENT_MODELS

**Prioritet: 🔴 KÄRNA — gör detta FÖRE T4 annars syns inte "builder" i inställnings-UI**

**Fil:** `app.py`, konstanten `_DEFAULT_AGENT_MODELS` (~rad 54).

Sök på `"krypto":` (sista raden i modell-dict). Lägg till direkt efter:
```python
    # Byggagenten — Claude Sonnet via Anthropic native API (ej OpenRouter)
    "builder":     "claude-sonnet-4-6",
```

OBS: Alla andra agenter i `_DEFAULT_AGENT_MODELS` använder OpenRouter-format (`"anthropic/claude-sonnet-4.6"`).
`"builder"` är undantaget — den anropar `anthropic.AsyncAnthropic` direkt och behöver native-format.

**Verifiera:** `GET /api/models` → `agent_ids`-listan ska innehålla `"builder"`.

---

## T4b — Backend: project_context_snapshot sparas vid /send

**Prioritet: 🔴 KÄRNA — gör detta FÖRE T4, annars har SSE-endpointen ingen kontext**

**Fil:** `app.py`, funktion `send_build_queue_item()` (~rad 531).

Sök på `"project_context": build_project_context(profile)` — det är i `job`-dict:et som returneras.
Lägg till INNAN `job = {...}` (dvs. spara till item-objektet):

```python
    # Spara spec + kontext på item-objektet så SSE-endpointen kan läsa utan att
    # behöva payload från frontend (som kan saknas vid reconnect).
    with _queue_lock:
        items = _queue_load()
        it_snap = next((i for i in items if i.get("id") == item_id), None)
        if it_snap:
            it_snap["project_context_snapshot"] = {
                "spec_markdown": it_snap.get("spec_markdown", ""),
                "context": build_project_context(profile),
                "profile": profile,
            }
            _queue_write(items)
```

**Verifiera:** Klicka "▶ Bygg nästa" → öppna `build_queue.json` → item ska ha `project_context_snapshot`-nyckeln.

---

## T4 — Backend: SSE-endpoint + BUILDER_TOOLS + agentic loop

**Prioritet: 🔴 KÄRNA — hela chatboxen är beroende av detta**
**Kräver: T4a och T4b klara först**

**Fil:** `app.py`

**Steg 1 — Lägg till imports och modul-level state** (efter `executor = ThreadPoolExecutor(...)`):

```python
# Lägg till StreamingResponse i befintlig import-rad:
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi import Request
import subprocess, re

# Builder agent state — keyed by item_id
_active_builders: dict[str, asyncio.Task] = {}
_builder_histories: dict[str, list[dict]] = {}
_builder_lock = threading.Lock()
_cancel_flags: dict[str, asyncio.Event] = {}
```

**Steg 2 — BUILDER_TOOLS konstant** (lägg till efter `_cancel_flags`):

```python
BUILDER_TOOLS = [
    {
        "name": "read_file",
        "description": "Läs ett utsnitt av en fil (max 12 000 tecken). Använd line_start/line_end för att läsa delar av stora filer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relativ sökväg från repo-rot"},
                "line_start": {"type": "integer", "description": "Första rad (1-indexerad). Standard: 1"},
                "line_end": {"type": "integer", "description": "Sista rad inklusiv. Standard: läs max 300 rader"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Skriv hela innehållet i en fil. VARNING: skriver över allt. Använd patch_file för partiella ändringar i stora filer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "patch_file",
        "description": "Ersätt en exakt textsträng i en fil med ny text. Säkrare än write_file för stora filer. Misslyckas om old_string inte hittas exakt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string", "description": "Exakt text att ersätta — måste vara unik i filen"},
                "new_string": {"type": "string", "description": "Text att sätta in istället"}
            },
            "required": ["path", "old_string", "new_string"]
        }
    },
    {
        "name": "search_file",
        "description": "Sök efter ett regex-mönster i en fil. Returnerar matchande rader med radnummer och kontext.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "pattern": {"type": "string", "description": "Python regex"},
                "context_lines": {"type": "integer", "description": "Rader kontext runt varje träff. Standard: 3"}
            },
            "required": ["path", "pattern"]
        }
    },
    {
        "name": "list_dir",
        "description": "Lista filer i en katalog.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relativ sökväg. Standard: repo-rot"}
            }
        }
    },
    {
        "name": "run_git",
        "description": "Kör ett git-kommando. Tillåtna kommandon: add, commit, push, status, diff, log.",
        "input_schema": {
            "type": "object",
            "properties": {
                "args": {"type": "array", "items": {"type": "string"}, "description": "Argument till git, t.ex. ['add', '-A'] eller ['commit', '-m', 'feat: ...']"}
            },
            "required": ["args"]
        }
    },
    {
        "name": "report_done",
        "description": "Anropa när all kod är skriven och pushad. Triggar automatisk granskning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Kort sammanfattning av vad som byggdes"}
            },
            "required": ["summary"]
        }
    }
]
```

**Steg 3 — Hjälpfunktioner** (lägg till nära `BUILDER_TOOLS`):

```python
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

def _sse_err(msg: str) -> str:
    return f"data: {json.dumps({'type': 'error', 'text': msg})}\n\n"

SECRET_PATTERNS = [
    r"sk-ant-api\w{20,}", r"ghp_[A-Za-z0-9]{36}", r"sk-or-v1-[A-Za-z0-9]{60,}",
    r"eyJhbGciOiJIUzI1NiJ9\.\w+", r"AKIA[A-Z0-9]{16}",
]

def _check_secrets(content: str) -> str | None:
    for pat in SECRET_PATTERNS:
        if re.search(pat, content):
            return "Filen verkar innehålla en hemlig nyckel. Använd settings.json eller miljövariabel."
    return None

async def _run_cmd(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Kör subprocess i executor — blockerar aldrig event loop."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        lambda: subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
    )
    return result.returncode, result.stdout, result.stderr

def _exec_tool(name: str, inp: dict, repo_path: Path) -> dict:
    """Exekverar ett BUILDER_TOOLS-verktyg synkront (kallas via run_in_executor)."""
    try:
        if name == "read_file":
            path = repo_path / inp["path"]
            try:
                path.resolve().relative_to(repo_path.resolve())
            except ValueError:
                return {"error": "Path traversal ej tillåtet."}
            if not path.exists():
                return {"error": f"Filen finns inte: {inp['path']}"}
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(0, (inp.get("line_start") or 1) - 1)
            end = min(len(lines), inp.get("line_end") or start + 300)
            chunk = "\n".join(f"{start+i+1}: {l}" for i, l in enumerate(lines[start:end]))
            if len(chunk) > 12000:
                chunk = chunk[:12000] + "\n... [TRUNKERAT — använd line_start/line_end för att läsa vidare]"
            return {"content": chunk, "total_lines": len(lines)}

        elif name == "write_file":
            path = repo_path / inp["path"]
            try:
                path.resolve().relative_to(repo_path.resolve())
            except ValueError:
                return {"error": "Path traversal ej tillåtet."}
            content = inp["content"]
            err = _check_secrets(content)
            if err:
                return {"error": err}
            # Atomisk skrivning via tmp
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return {"ok": True, "bytes": len(content.encode())}

        elif name == "patch_file":
            path = repo_path / inp["path"]
            try:
                path.resolve().relative_to(repo_path.resolve())
            except ValueError:
                return {"error": "Path traversal ej tillåtet."}
            if not path.exists():
                return {"error": f"Filen finns inte: {inp['path']}"}
            old, new = inp["old_string"], inp["new_string"]
            err = _check_secrets(new)
            if err:
                return {"error": err}
            text = path.read_text(encoding="utf-8")
            count = text.count(old)
            if count == 0:
                return {"error": f"old_string hittades inte i {inp['path']}. Kontrollera exakt stavning/whitespace."}
            if count > 1:
                return {"error": f"old_string hittades {count} gånger — måste vara unik. Ge mer kontext."}
            new_text = text.replace(old, new, 1)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(new_text, encoding="utf-8")
            tmp.replace(path)
            return {"ok": True}

        elif name == "search_file":
            path = repo_path / inp["path"]
            if not path.exists():
                return {"error": f"Filen finns inte: {inp['path']}"}
            ctx = inp.get("context_lines", 3)
            pattern = inp["pattern"]
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            results = []
            for i, line in enumerate(lines):
                if re.search(pattern, line):
                    start = max(0, i - ctx)
                    end = min(len(lines), i + ctx + 1)
                    block = "\n".join(f"{start+j+1}: {lines[start+j]}" for j in range(end - start))
                    results.append(block)
            if not results:
                return {"matches": 0, "content": "Inga träffar."}
            combined = "\n---\n".join(results[:20])
            if len(combined) > 8000:
                combined = combined[:8000] + "\n... [TRUNKERAT]"
            return {"matches": len(results), "content": combined}

        elif name == "list_dir":
            p = repo_path / (inp.get("path") or ".")
            if not p.is_dir():
                return {"error": "Inte en katalog."}
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            return {"entries": [{"name": e.name, "type": "dir" if e.is_dir() else "file"} for e in entries[:100]]}

        elif name == "report_done":
            # Signalerar att agenten är klar — faktisk callback sker i generatorn
            return {"ok": True, "summary": inp.get("summary", "")}

        else:
            return {"error": f"Okänt verktyg: {name}"}

    except Exception as e:
        return {"error": str(e)}
```

**Steg 4 — run_git körs separat** (behöver async — implementeras i generatorn):

Inuti `generate()`-generatorn, i `_exec_tool_async()`-wrappern:
```python
async def _exec_tool_async(name: str, inp: dict) -> dict:
    if name == "run_git":
        GIT_WHITELIST = {"add", "commit", "push", "status", "diff", "log"}
        args = inp.get("args", [])
        if not args or args[0] not in GIT_WHITELIST:
            return {"error": f"git {args[0] if args else '?'} är inte tillåtet."}
        rc, out, err = await _run_cmd(["git"] + args, cwd=str(repo_path))
        return {"returncode": rc, "stdout": out[:3000], "stderr": err[:500]}
    else:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(executor, lambda: _exec_tool(name, inp, repo_path))
```

**Steg 5 — SSE-endpoint** (lägg till i app.py, efter BUILDER_TOOLS-definitionerna):

```python
@app.get("/api/builder/stream/{item_id}")
async def builder_stream(item_id: str, request: Request):
    s = load_settings()
    repo_path = Path(s.get("local_path") or str(BASE_DIR))

    async def generate():
        # ── Pre-flight ──
        if not repo_path.exists():
            yield _sse_err(f"Lokal sökväg finns inte: {repo_path}"); return

        with _queue_lock:
            items = _queue_load()
            item = next((i for i in items if i.get("id") == item_id
                         and not i.get("deleted_at")), None)
        if not item:
            yield _sse_err("Ärende hittades inte."); return
        if item["status"] != "byggs":
            yield _sse_err(f"Felaktig status: {item['status']} — förväntat 'byggs'."); return

        spec = item.get("project_context_snapshot") or item.get("spec_markdown", "")
        if not spec.strip():
            yield _sse_err("Spec saknas — postad ett tomt ärende?"); return

        # Git pre-flight
        rc, out, err = await _run_cmd(["git", "remote", "get-url", "origin"], cwd=str(repo_path))
        if rc != 0:
            yield _sse({"type": "warning", "text": "⚠️ Inget git remote 'origin' — push kommer att misslyckas."})
        else:
            yield _sse({"type": "status", "text": f"✅ Repo: {out.strip()}"})

        # Pre-commit om dirty tree
        rc2, _, _ = await _run_cmd(["git", "status", "--porcelain"], cwd=str(repo_path))

        yield _sse({"type": "status", "text": "🔍 Förbereder..."})

        # ── System prompt ──
        system = (
            "Du är en senior fullstack-ingenjör som bygger features i ett befintligt projekt.\n"
            "Repo finns lokalt. Du har verktyg för att läsa, skriva och patcha filer, söka i kod "
            "och köra git-kommandon.\n\n"
            "REGLER:\n"
            "1. Läs ALDRIG hela app.py eller index.html — de är 4000+ rader. "
            "Använd search_file för att hitta rätt sektion, sedan read_file med line_start/line_end.\n"
            "2. Använd patch_file för ändringar i stora filer — INTE write_file.\n"
            "3. Kontrollera att index.html slutar med </html> innan du committar.\n"
            "4. Committa med: git add -A → git commit -m 'feat: ...' → git push origin HEAD.\n"
            "5. Anropa report_done när allt är pushat.\n"
            "6. Skriv ALDRIG API-nycklar eller tokens i kod.\n"
            "7. Alla statusmeddelanden till användaren ska vara på svenska och fri från teknisk jargong.\n\n"
            f"SPEC:\n{spec}"
        )

        messages: list[dict] = []
        if item_id in _builder_histories and _builder_histories[item_id]:
            messages = list(_builder_histories[item_id])

        # ── Agentic loop ──
        # Normalisera: OpenRouter "anthropic/claude-sonnet-4.6" → native "claude-sonnet-4-6"
        raw_model = get_agent_model("builder", "claude-sonnet-4-6")
        builder_model = raw_model.strip().removeprefix("anthropic/").replace(".", "-")
        api_client = anthropic.AsyncAnthropic(api_key=s.get("api_key", ""), timeout=120.0)
        turn = 0
        MAX_TURNS = 30
        report_done_called = False

        async def _exec_tool_async(name: str, inp: dict) -> dict:
            if name == "run_git":
                GIT_WHITELIST = {"add", "commit", "push", "status", "diff", "log"}
                args = inp.get("args", [])
                if not args or args[0] not in GIT_WHITELIST:
                    return {"error": f"git {args[0] if args else '?'} är inte tillåtet."}
                rc, out, err = await _run_cmd(["git"] + args, cwd=str(repo_path))
                return {"returncode": rc, "stdout": out[:3000], "stderr": err[:500]}
            else:
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(executor, lambda: _exec_tool(name, inp, repo_path))

        while turn < MAX_TURNS and not report_done_called:
            turn += 1

            # Avbryt om klient kopplat från
            if await request.is_disconnected():
                return

            # Avbryt om cancel_flag satt
            if _cancel_flags.get(item_id, asyncio.Event()).is_set():
                yield _sse({"type": "status", "text": "🛑 Bygget avbröts."})
                return

            # API-anrop med keepalive
            api_task = asyncio.create_task(api_client.messages.create(
                model=builder_model, max_tokens=8192,
                system=system, tools=BUILDER_TOOLS, messages=messages,
            ))
            while not api_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(api_task), timeout=15)
                    break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

            try:
                response = api_task.result()
            except Exception as e:
                yield _sse_err(f"Något gick fel. Försöker igen... 🔄")
                return

            # Extrahera text och tool_use
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            tool_calls = [b for b in response.content if b.type == "tool_use"]

            if text_parts:
                full_text = "\n".join(text_parts)
                yield _sse({"type": "text", "text": full_text})

            messages.append({"role": "assistant", "content": response.content})
            _builder_histories[item_id] = messages[-40:]  # max 40 turns

            if response.stop_reason == "end_turn" or not tool_calls:
                break

            # Kör verktyg
            tool_results = []
            for tc in tool_calls:
                friendly = {
                    "read_file": "📖 Läser fil...", "write_file": "✏️ Skriver fil...",
                    "patch_file": "🔧 Uppdaterar fil...", "search_file": "🔍 Söker i kod...",
                    "list_dir": "📂 Tittar i mappen...", "run_git": None,  # dölj git
                    "report_done": "💾 Sparar allt..."
                }.get(tc.name, "🔧 Arbetar...")
                if friendly:
                    yield _sse({"type": "tool_start", "tool": tc.name, "label": friendly})

                result = await _exec_tool_async(tc.name, tc.input)

                if tc.name == "report_done":
                    report_done_called = True
                    yield _sse({"type": "status", "text": "✅ Klart! Jag sparade ändringarna."})

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })

            messages.append({"role": "user", "content": tool_results})

        if not report_done_called:
            yield _sse({"type": "status",
                        "text": "⚠️ Max antal steg nått — committar det som gjorts."})
            await _exec_tool_async("run_git", {"args": ["add", "-A"]})
            await _exec_tool_async("run_git", {"args": ["commit", "-m", "wip: max turns reached — partial build"]})
            await _exec_tool_async("run_git", {"args": ["push", "origin", "HEAD"]})

        # ── Auto-granskning ──
        yield _sse({"type": "status", "text": "🔍 Kontrollerar resultatet..."})
        try:
            code_resp = await github_fetch({
                "repo": s.get("self_repo", ""), "branch": s.get("self_branch", "main"),
                "github_token": s.get("github_token", "")
            })
            # github_fetch returnerar JSONResponse vid fel (t.ex. saknat repo) — se fallgrop F4
            if not isinstance(code_resp, dict):
                yield _sse({"type": "warning", "text": "⚠️ Kunde inte hämta kod från GitHub — kontrollera repo/branch i projektet."})
                return
            code = code_resp.get("code", "")
            profile = item.get("project_context_snapshot") or {}
            review_result = await build_queue_review(item_id, {
                "code": code, "images": [], "profile": profile
            })
            run_id = review_result.get("run_id") or review_result.get("id", "")
            new_status = review_result.get("new_status", "behover_dig")
            verdict = review_result.get("verdict", {})
            if new_status == "klar":
                yield _sse({"type": "verdict", "status": "klar",
                            "text": "✅ Klart! Allt godkänt.", "run_id": run_id})
            else:
                kvar = verdict.get("kvarstaende", [])
                yield _sse({"type": "verdict", "status": "behover_dig",
                            "text": "🙋 Jag behöver din hjälp — något saknades.",
                            "kvarstaende": kvar, "run_id": run_id})
        except Exception as e:
            yield _sse({"type": "warning", "text": "Granskning misslyckades — kontrollera manuellt."})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.delete("/api/builder/stream/{item_id}")
async def cancel_builder(item_id: str):
    flag = asyncio.Event()
    flag.set()
    _cancel_flags[item_id] = flag
    # Återställ till kö
    with _queue_lock:
        items = _queue_load()
        for it in items:
            if it.get("id") == item_id and it.get("status") == "byggs":
                it["status"] = "kö"
                _queue_log(it, "cancelled", "användaren avbröt bygget")
        _queue_write(items)
    return {"ok": True}


@app.post("/api/builder/followup/{item_id}")
async def builder_followup(item_id: str, payload: dict):
    """Lägg till ett följdmeddelande i pågående builder-session."""
    msg = payload.get("message", "").strip()
    if not msg:
        return JSONResponse({"error": "Tomt meddelande."}, status_code=400)
    hist = _builder_histories.get(item_id, [])
    hist.append({"role": "user", "content": msg})
    _builder_histories[item_id] = hist
    return {"ok": True, "turns": len(hist)}


@app.get("/api/builder/status/{item_id}")
async def builder_status(item_id: str):
    return {"running": item_id in _active_builders and not _active_builders[item_id].done()}
```

**Verifiera:** `curl http://localhost:8001/api/builder/status/test` ska returnera `{"running": false}`.

---

## T5 — Frontend: #builderPanel HTML + CSS

**Prioritet: 🟡 — visuell container för chatboxen**

**Fil:** `index.html`

**Var:** Direkt efter stängningstaggen för `#attByggaView` (sök på `</div><!-- /attByggaView -->`
eller den sista `</div>` i attByggaView-sektionen), lägg till:

```html
<!-- BUILDER PANEL — split-view chatt -->
<div id="builderPanel" class="builder-panel">
  <div class="builder-header">
    <div class="builder-header-left">
      <span id="builderTitle">💬 Bygger...</span>
      <div id="builderSteps" class="builder-steps">
        <span class="step" data-step="preflight">Förbereder</span>
        <span class="step-sep">›</span>
        <span class="step" data-step="building">Bygger</span>
        <span class="step-sep">›</span>
        <span class="step" data-step="pushing">Sparar</span>
        <span class="step-sep">›</span>
        <span class="step" data-step="reviewing">Kontrollerar</span>
        <span class="step-sep">›</span>
        <span class="step" data-step="done">Klart!</span>
      </div>
    </div>
    <button class="btn btn-ghost builder-close" onclick="cancelBuilder()" title="Avbryt och stäng">✕ Avbryt</button>
  </div>
  <div id="builderMessages" class="builder-messages"></div>
  <div id="builderVerdict" class="builder-verdict" style="display:none;"></div>
  <div class="builder-input-row" id="builderInputRow" style="display:none;">
    <input type="text" id="builderInput" class="builder-input" placeholder="Skriv ett meddelande...">
    <button class="btn btn-primary" onclick="sendBuilderMessage()">Skicka</button>
  </div>
</div>
```

**CSS** (lägg till i `<style>`-blocket):

```css
/* ── BUILDER PANEL ── */
#builderPanel {
  width: 420px; min-width: 320px; max-width: 480px;
  display: none; flex-direction: column;
  border-left: 1px solid var(--border);
  background: var(--bg1);
  height: 100%;
}
body.view-bygga.builder-active #attByggaView {
  max-width: calc(100% - 420px); overflow-y: auto;
}
body.view-bygga.builder-active #builderPanel { display: flex; }
body:not(.view-bygga) #builderPanel { display: none !important; }

.builder-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  background: var(--bg2); gap: 8px;
}
.builder-header-left { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
#builderTitle { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.builder-steps { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text3); }
.builder-steps .step { transition: color .2s, font-weight .2s; }
.builder-steps .step.active { color: var(--accent); font-weight: 600; }
.builder-steps .step.done-step { color: var(--success, #4caf50); }
.builder-steps .step-sep { color: var(--text3); }
.builder-close { font-size: 12px; padding: 4px 10px; white-space: nowrap; }

.builder-messages {
  flex: 1; overflow-y: auto; padding: 12px;
  display: flex; flex-direction: column; gap: 8px;
}
.builder-msg { padding: 8px 12px; border-radius: 8px; font-size: 13px; line-height: 1.5; }
.builder-msg.agent { background: var(--bg2); border: 1px solid var(--border); }
.builder-msg.system { color: var(--text3); font-size: 12px; padding: 4px 8px; }
.builder-msg.user { background: var(--accent); color: white; align-self: flex-end; max-width: 80%; }
.builder-msg.error { background: #fee; border: 1px solid #f88; color: #c00; }

/* Kollapsade tool-anrop */
.builder-tool-block {
  background: var(--bg2); border: 1px solid var(--border);
  border-radius: 4px; font-size: 11px;
}
.builder-tool-summary {
  padding: 3px 8px; cursor: pointer; color: var(--text3);
  list-style: none; display: flex; gap: 6px; align-items: center;
}
.builder-tool-summary:hover { color: var(--text2); }
.builder-tool-detail {
  padding: 4px 8px 6px; font-family: monospace; font-size: 10px;
  white-space: pre-wrap; word-break: break-all;
  border-top: 1px solid var(--border); color: var(--text2);
}

/* Verdict-banner */
.builder-verdict { padding: 12px 14px; border-top: 1px solid var(--border); }
.builder-verdict.klar { background: #e8f5e9; border-color: #4caf50; }
.builder-verdict.behover-dig { background: #fff3e0; border-color: #ff9800; }
.builder-verdict-title { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.builder-verdict-list { font-size: 12px; color: var(--text2); padding-left: 16px; }

.builder-input-row {
  display: flex; gap: 8px; padding: 10px 12px;
  border-top: 1px solid var(--border); background: var(--bg2);
}
.builder-input { flex: 1; padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; background: var(--bg1); color: var(--text1); }
```

**Verifiera:** Lägg tillfälligt till `builder-active` på `<body>` i DevTools → panelen ska synas till höger om kövisningen.

---

## T6 — Frontend: builder JS

**Prioritet: 🟡 — logiken som kopplar ihop UI med SSE-strömmen**

**Fil:** `index.html` — lägg till följande funktioner i `<script>`-blocket.

```javascript
// ── BUILDER STATE ──
let _builderESS = null;
let _currentBuilderId = null;

const _TOOL_LABELS = {
  read_file:   '📖 Läser filen...',
  write_file:  '✏️ Skriver filen...',
  patch_file:  '🔧 Uppdaterar filen...',
  search_file: '🔍 Söker i koden...',
  list_dir:    '📂 Tittar i mappen...',
  report_done: '💾 Sparar allt...',
  // run_git visas ALDRIG
};

const _BUILD_STEPS = ['preflight','building','pushing','reviewing','done'];

function _setBuilderStep(step) {
  document.querySelectorAll('.builder-steps .step').forEach(el => {
    const s = el.dataset.step;
    el.classList.remove('active', 'done-step');
    const idx = _BUILD_STEPS.indexOf(s);
    const cur = _BUILD_STEPS.indexOf(step);
    if (idx < cur) el.classList.add('done-step');
    else if (idx === cur) el.classList.add('active');
  });
}

function _appendBuilderMsg(type, text) {
  const el = document.createElement('div');
  el.className = 'builder-msg ' + type;
  el.textContent = text;
  document.getElementById('builderMessages').appendChild(el);
  el.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return el;
}

function _appendToolRow(label) {
  const details = document.createElement('details');
  details.className = 'builder-tool-block';
  details.innerHTML = `<summary class="builder-tool-summary">${escHtml(label)}</summary>`;
  document.getElementById('builderMessages').appendChild(details);
  details.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return details;
}

function _handleBuilderEvent(msg) {
  switch (msg.type) {
    case 'status':
      _appendBuilderMsg('system', msg.text);
      if (msg.text.includes('Förbereder')) _setBuilderStep('preflight');
      else if (msg.text.includes('Bygger') || msg.text.includes('Skriver')) _setBuilderStep('building');
      else if (msg.text.includes('Sparar')) _setBuilderStep('pushing');
      else if (msg.text.includes('Kontrollerar')) _setBuilderStep('reviewing');
      break;
    case 'text':
      _appendBuilderMsg('agent', msg.text);
      break;
    case 'tool_start':
      if (_TOOL_LABELS[msg.tool]) _appendToolRow(_TOOL_LABELS[msg.tool]);
      break;
    case 'error':
      _appendBuilderMsg('error', msg.text);
      break;
    case 'verdict':
      _setBuilderStep('done');
      const vd = document.getElementById('builderVerdict');
      vd.style.display = '';
      vd.className = 'builder-verdict ' + (msg.status === 'klar' ? 'klar' : 'behover-dig');
      const items = (msg.kvarstaende || []).map(k => `<li>${escHtml(k)}</li>`).join('');
      vd.innerHTML = `<div class="builder-verdict-title">${escHtml(msg.text)}</div>`
        + (items ? `<ul class="builder-verdict-list">${items}</ul>` : '');
      document.getElementById('builderInputRow').style.display = 'flex';
      loadAttBygga();
      break;
    case 'review_started':
      // Spara recovery-info för page refresh
      if (msg.run_id) {
        sessionStorage.setItem('builder_recovery_' + _currentBuilderId,
          JSON.stringify({ run_id: msg.run_id, url: msg.recovery_url, ts: Date.now() }));
      }
      break;
  }
}

function openBuilderPanel(itemId) {
  _currentBuilderId = itemId;
  document.getElementById('builderMessages').innerHTML = '';
  document.getElementById('builderVerdict').style.display = 'none';
  document.getElementById('builderVerdict').innerHTML = '';
  document.getElementById('builderInputRow').style.display = 'none';
  document.getElementById('builderTitle').textContent = '💬 Bygger...';
  _setBuilderStep('preflight');
  document.body.classList.add('builder-active');

  // Starta SSE
  if (_builderESS) _builderESS.close();
  _builderESS = new EventSource('/api/builder/stream/' + itemId);
  _builderESS.onmessage = (e) => {
    try { _handleBuilderEvent(JSON.parse(e.data)); } catch {}
  };
  _builderESS.onerror = () => {
    _appendBuilderMsg('system', 'Anslutning bruten — försöker återansluta...');
  };
}

async function cancelBuilder() {
  if (_currentBuilderId) {
    await fetch('/api/builder/stream/' + _currentBuilderId, { method: 'DELETE' });
  }
  if (_builderESS) { _builderESS.close(); _builderESS = null; }
  document.body.classList.remove('builder-active');
  _currentBuilderId = null;
  loadAttBygga();
}

async function sendBuilderMessage() {
  const input = document.getElementById('builderInput');
  const msg = input.value.trim();
  if (!msg || !_currentBuilderId) return;
  input.value = '';
  _appendBuilderMsg('user', msg);
  await fetch('/api/builder/followup/' + _currentBuilderId, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: msg })
  });
}
```

**Verifiera:** `openBuilderPanel('test-id')` ska öppna panelen och starta en SSE-anslutning.

---

## T7 — Frontend: ersätt startBuild clipboard med openBuilderPanel

**Prioritet: 🟡 — kopplar ihop bygga-knappen med chatboxen**

**Fil:** `index.html`, funktion `startBuild()` (~rad 2111).

**Sök på:**
```javascript
    await navigator.clipboard.writeText(spec).catch(() => {});
    showToast(data.job?.spec_rewritten
```

**Ersätt hela toast+clipboard-blocket med:**
```javascript
    openBuilderPanel(id);
```

Hela `startBuild()` ska alltså bli:
```javascript
async function startBuild(id, btn) {
  const it = _queueItems.find(x => x.id === id);
  const isRetry = it?.status === 'behover_dig' && (it?.last_verdict?.kvarstaende || []).length;
  if (btn) { btn.disabled = true; btn.textContent = isRetry ? '⏳ Promptsmeden skriver om specen...' : '⏳...'; }
  try {
    const res = await fetch('/api/build-queue/' + id + '/send', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ byggsatt: getActiveProject()?.profile?.byggsatt || {},
                             profile: { ...(getActiveProject()?.profile || {}), name: getActiveProject()?.name || '' } })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'HTTP ' + res.status);
    await loadAttBygga();
    openBuilderPanel(id);
  } catch (e) {
    showToast('❌ ' + e.message);
    if (btn) { btn.disabled = false; btn.textContent = isRetry ? '🔄 Försök igen' : '▶ Bygg det här!'; }
  }
}
```

**Verifiera:** Klicka "▶ Bygg det här!" → panelen öppnas istället för att toasten visas.

---

## T8 — Frontend: renderQueueBox — barnvänliga knappar + data-item-id

**Prioritet: 🟡 — uppdaterar knapparna, statustexter och lägger till data-item-id (behövs av T12)**

**Fil:** `index.html`, funktion `renderQueueBox()` (~rad 2001).

**Steg 1 — Lägg till `data-item-id` på queue-korten** (se fallgrop F3):

Sök på raden som returnerar kortets HTML (ca rad 2061):
```javascript
return `<div class="queue-card ${expanded ? 'expanded' : ''} st-${it.status}">
```
Ersätt med:
```javascript
return `<div class="queue-card ${expanded ? 'expanded' : ''} st-${it.status}" data-item-id="${it.id}">
```

**Steg 2 — `kö`-status** — ändra hjälptext:
```javascript
// Sök på: "Specen kopieras"
// Ersätt med:
'Tryck för att börja bygga 🚀'
```

**Steg 3 — `byggs`-status** — ersätt knappar:
```javascript
// Sök på: "kontrolleraBuild"
// Ersätt hela actions-strängen för byggs med:
actions = `<button class="btn btn-primary" onclick="openBuilderPanel('${it.id}')">💬 Visa vad som händer</button>
           <button class="btn btn-ghost" onclick="queueSetStatus('${it.id}','kö')" style="font-size:11px;">← Avbryt, vänta istället</button>`;
```

**Steg 4 — Status-badges** (alla status-lägen):
```javascript
// Uppdatera statusText-mappningen (sök på "st-klar" eller befintlig status-badge-logik):
const statusText = {
  'kö':          '🕐 Väntar på sin tur',
  'byggs':       '⏳ Håller på att byggas...',
  'klar':        '✅ Klart!',
  'behover_dig': '🙋 Jag behöver din hjälp!'
}[it.status] || it.status;
```

**Steg 5 — `behover_dig`-retry-knapp:**
```javascript
// Sök på: "Skicka igen (specen skrivs om"
// Ersätt med:
'🔄 Försök igen'
```

**Verifiera:** Inspektera ett kö-kort i DevTools → ska ha `data-item-id`-attribut och barnvänliga texter.

---

## T9 — Settings UI: lägg till local_path-fält

**Prioritet: 🟡 — utan detta kan byggaren inte konfigurera var repot ligger**

**Fil:** `index.html`

**I settings-modalens HTML** (efter `selfRepoInput`-blocket, ~rad 1057), lägg till:
```html
<div class="form-group">
  <label>Lokal repo-sökväg <span style="font-weight:400;color:var(--text3)">(för byggagenten)</span></label>
  <input type="text" id="localPathInput" placeholder="C:\innob-agent\prompt-team" style="font-family:monospace;font-size:12px;">
  <div style="font-size:11px;color:var(--text3);margin-top:4px;">Mappen där koden finns lokalt. Standard: appens egen mapp.</div>
</div>
```

**I `openSettings()`** — lägg till efter `document.getElementById('selfRepoInput').value = s.self_repo || '';`:
```javascript
document.getElementById('localPathInput').value = s.local_path || '';
```

**I `saveSettings()`** — lägg till i `payload`-objektet:
```javascript
const localPath = document.getElementById('localPathInput').value.trim();
if (localPath) payload.local_path = localPath;
```

**Verifiera:** Öppna Inställningar → ange en sökväg → Spara → öppna igen → sökvägen ska finnas kvar.

---

## T11 — Frontend: AGENT_DISPLAY_NAMES — komplettera alla agenter

**Prioritet: 🟢 — kosmetisk men viktig för inställnings-UI (modell-per-agent-vyn)**

**Fil:** `index.html`, `AGENT_DISPLAY_NAMES`-konstanten (~rad 1357).

**Vad som är fel nu:** Objektet har bara 8 poster. Systemet har ~35 agenter. Saknade agenter visas med ID-sträng istället för namn i UI.

**Ersätt hela objektet med:**
```javascript
const AGENT_DISPLAY_NAMES = {
  kravanalytikern:          '📋 Kravanalytikern',
  architecture:             '🏗️ Arkitekten',
  ux:                       '🎨 UX-agenten',
  ui_design:                '🖌️ UI-agenten',
  frontend:                 '🧱 Frontend-agenten',
  responsive:               '📱 Responsivitetsagenten',
  accessibility:            '♿ Tillgänglighetsagenten',
  database:                 '🗄️ Databasagenten',
  datamigration:            '🔄 Datamigrationsagenten',
  api:                      '🔌 API-agenten',
  backend:                  '⚙️ Backend-agenten',
  error_handling:           '🚨 Felhanteringsagenten',
  edge_case:                '🔬 Edge-case-agenten',
  security:                 '🛡️ Säkerhetsagenten',
  hemlighetsvakten:         '🔑 Hemlighetsvakten',
  dataskyddsjuristen:       '⚖️ Dataskyddsjuristen',
  hotmodelleraren:          '🎯 Hotmodelleraren',
  performance:              '⚡ Prestandaagenten',
  scalability:              '📈 Skalbarhetssagenten',
  data_privacy:             '🔒 Dataintegritetssagenten',
  testing:                  '🧪 Testaren',
  visual_qa:                '👁️ Visual QA-agenten',
  rotorsak:                 '🔍 Rotorsaksanalytikern',
  risk:                     '⚠️ Riskvärderaren',
  integration:              '🔗 Integrationsanalytikern',
  code_quality:             '✨ Kodkvalitetsagenten',
  devops:                   '🚀 DevOps/CI-CD-agenten',
  ai_ml:                    '🤖 AI/ML-agenten',
  dokumentation:            '📜 Dokumentationsagenten',
  licens:                   '📋 Licensagenten',
  i18n:                     '🌍 I18n-agenten',
  observability:            '📊 Observabilitetsagenten',
  concurrency:              '🧵 Trådsäkerhetsagenten',
  krypto:                   '🔐 Kryptoagenten',
  agent_arkitektur:         '🤖 Agentarkitekturagenten',
  backloghallaren:          '📦 Backloghållaren',
  planeraren:               '📐 Planeraren',
  prompt_smith:             '✍️ Promptsmeden',
  completeness:             '✅ Kompletthetsgranskaren',
  bestallarsammanfattaren:  '📝 Beställarsammanfattaren',
  builder:                  '🏗️ Byggagenten',
};
```

**Verifiera:** Inställningar → "Modell per agent" → alla rader ska ha svenska namn, inklusive "🏗️ Byggagenten".

---

## T12 — Frontend: Reconnect-knapp vid page refresh

**Prioritet: 🟢 — QoL om webbläsaren laddas om under pågående bygge**
**Kräver: T8 klar (data-item-id måste finnas på korten)**

**Fil:** `index.html`, funktion `loadAttBygga()`.

Sök på `renderQueueBox()` i `loadAttBygga()`. Lägg till direkt EFTER anropet:

```javascript
// Reconnect: kolla om något byggs-item har recovery-session från före page refresh
_queueItems.filter(it => it.status === 'byggs').forEach(it => {
  const stored = sessionStorage.getItem('builder_recovery_' + it.id);
  if (!stored) return;
  try {
    const { ts } = JSON.parse(stored);
    if (Date.now() - ts > 30 * 60 * 1000) return;  // äldre än 30 min — skippa
    // Hitta kortets action-rad via data-item-id (satt i T8)
    const card = document.querySelector('[data-item-id="' + it.id + '"]');
    if (!card) return;
    const actions = card.querySelector('.qc-actions');
    if (!actions) return;
    const btn = document.createElement('button');
    btn.className = 'btn btn-ghost';
    btn.style.cssText = 'font-size:11px;margin-top:4px;';
    btn.textContent = '💬 Återanslut till pågående bygge';
    btn.onclick = () => openBuilderPanel(it.id);
    actions.prepend(btn);
  } catch {}
});
```

**Verifiera:**
1. Starta ett bygge → ladda om sidan
2. "Återanslut"-knapp ska synas på det aktiva kortet
3. Knappen ska öppna panelen och återansluta till SSE-strömmen


---

## T4c — Frontend: per-projekt agent-inaktivering UI

**Prioritet: 🟢 — backend-API finns (working tree), ingen frontend ännu**

Server har sedan 2026-06-10 (ostaged):
- `GET /api/projects/{id}/settings` — returnerar `disabled_agents` + komplett `agent_catalogue`
- `POST /api/projects/{id}/settings` — sparar `disabled_agents`-lista
- `_ALWAYS_RUN_AGENT_IDS` = `hemlighetsvakten` + `dataskyddsjuristen` — kan aldrig stängas av

**Var i index.html:** Settings-modal, under "Modell per agent"-sektionen.

**HTML** (lägg till):
```html
<div class="form-group" id="disabledAgentsSection" style="display:none;">
  <label>Stäng av agenter för detta projekt</label>
  <div id="disabledAgentsList" style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;"></div>
  <div style="font-size:11px;color:var(--text3);margin-top:4px;">
    Hemlighetsvakten och Dataskyddsjuristen kan aldrig stängas av.
  </div>
</div>
```

**JS — läs:**
```javascript
async function loadDisabledAgents(projectId) {
  if (!projectId) return;
  const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/settings`);
  if (!r.ok) return;
  const data = await r.json();
  const disabled = new Set(data.disabled_agents || []);
  const always   = new Set(data.always_run_agent_ids || []);
  const container = document.getElementById('disabledAgentsList');
  container.innerHTML = (data.agent_catalogue || []).map(a =>
    `<label style="font-size:12px;display:flex;align-items:center;gap:4px;cursor:pointer;">
       <input type="checkbox" data-agent="${a.id}"
              ${disabled.has(a.id) ? '' : 'checked'}
              ${always.has(a.id) ? 'disabled title="Kan inte inaktiveras"' : ''}>
       ${a.emoji} ${a.name}
     </label>`
  ).join('');
  document.getElementById('disabledAgentsSection').style.display = '';
}
```

**JS — spara:**
```javascript
async function saveDisabledAgents(projectId) {
  if (!projectId) return;
  const inputs = document.querySelectorAll('#disabledAgentsList input[type=checkbox]:not(:disabled)');
  const disabled = [...inputs].filter(i => !i.checked).map(i => i.dataset.agent);
  await fetch(`/api/projects/${encodeURIComponent(projectId)}/settings`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ disabled_agents: disabled })
  });
}
```

**Koppla in:**
- Anropa `loadDisabledAgents(getActiveProject()?.id)` i slutet av `openSettings()`
- Anropa `saveDisabledAgents(getActiveProject()?.id)` i `saveSettings()` före `fetch`-anropet

**Verifiera:** Inaktivera t.ex. `i18n` → kör en review → `i18n`-agenten ska inte synas i resultaten.

---

## STATUSÖVERSIKT — SLUTLIG (Iteration 9, 2026-06-10)

> Skicka EN task i taget. Rätt ordning: `T1 → T2 → T3 → T4a → T4b → T4 → T5 → T6 → T7 → T8 → T9 → T11 → T12`
> Refaktorering (`T13–T19`) kan parallelliseras med T4/T5 men kräver separat PR.
> `T4c` är oberoende, kan göras när T4 är mergad.
> **T10 = duplikat av T4b** — hoppa över T10 om T4b är gjord.

| ID | Uppgift | Prio | Est. | Status | Beroer på |
|---|---|---|---|---|---|
| T1 | Fixa index.html-truncation | 🔴 AKUT | 10 min | ❌ | — |
| T2 | Fixa switchView() wipes builder-active | 🔴 | 5 min | ❌ | T1 |
| T3 | Komplettera .gitignore | 🟡 | 5 min | ❌ | — |
| T4a | Backend: "builder" i `_DEFAULT_AGENT_MODELS` | 🔴 | 5 min | ❌ | — |
| T4b | Backend: `project_context_snapshot` vid /send | 🔴 | 20 min | ❌ | — |
| T4 | Backend: SSE-endpoint + BUILDER_TOOLS + loop | 🔴 KÄRNA | 4–6h | ❌ | T4a, T4b |
| T5 | Frontend: `#builderPanel` HTML + CSS | 🟡 | 1h | ❌ | T1 |
| T6 | Frontend: builder JS (SSE + events) | 🟡 | 2h | ❌ | T4, T5 |
| T7 | Frontend: ersätt clipboard med `openBuilderPanel()` | 🟡 | 30 min | ❌ | T6 |
| T8 | Frontend: `renderQueueBox` barnvänliga knappar | 🟡 | 30 min | ❌ | T6 |
| T9 | Settings UI: `local_path`-fält | 🟡 | 30 min | ❌ | T1 |
| T11 | Frontend: `AGENT_DISPLAY_NAMES` komplett (40+ agenter) | 🟢 | 15 min | ❌ | — |
| T12 | Frontend: Reconnect-knapp vid page refresh | 🟢 | 30 min | ❌ | T8 |
| T4c | Frontend: per-projekt agent-inaktivering UI | 🟢 | 45 min | ❌ | T4 |
| T13 | Extrahera `_backlog_write()` | 🔴 | 30 min | ❌ | — |
| T14 | Extrahera `_async_wrap()` | 🔴 | 30 min | ❌ | — |
| T15 | Extrahera `_run_synthesis_agent()` | 🔴 | 1h | ❌ | — |
| T16 | Cachelägg `_sb_available()` | 🟡 | 15 min | ❌ | — |
| T17 | Läs git-user från settings i `push_to_github.py` | 🟡 | 20 min | ❌ | — |
| T18 | Unit-tester för känsliga interna funktioner | 🟡 | 2h | ❌ | — |
| T19 | Extrahera `_parse_json_safe()` | 🟡 | 30 min | ❌ | — |

**Beroendegraf:**
```
T1 ──────────────┬──► T2
                 ├──► T5 ──► T6 ──► T7
                 │              └──► T8 ──► T12
                 └──► T9
T3 ─────────────────► (oberoende)
T4a ─────────────────┐
T4b ─────────────────┴──► T4 ──► T6
                              └──► T4c
T11 ────────────────► (oberoende)
T13/T14/T15/T16/T17/T18/T19 ─► (kan parallelliseras med T4/T5)
```

**PRINCIPREGEL:** Systemet pushar ALDRIG automatiskt till git. Push är alltid en manuell användaråtgärd.
