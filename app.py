"""
Prompt Team — AI-granskningsteam för pre- och post-build
Kör på port 8001
"""
import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import re
import threading
import uuid
from datetime import datetime
import httpx
import anthropic
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Prompt Team")
executor = ThreadPoolExecutor(max_workers=40)

@app.on_event("startup")
async def startup():
    _migrate_sessions()

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    # Locked to localhost origins — wildcard CORS let any website call this API
    # (which stores credentials and can burn OpenRouter credits).
    allow_origins=["http://localhost:8001", "http://127.0.0.1:8001"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_settings_lock = threading.Lock()

BASE_DIR = Path(__file__).parent
SETTINGS_FILE = BASE_DIR / "settings.json"

# ──────────────────────────────────────────────
# SETTINGS
# ──────────────────────────────────────────────

_DEFAULT_AGENT_MODELS = {
    # Gate: interprets the vague idea (runs once) — Gemini Flash is a proven safe pick here
    "kravanalytikern": "google/gemini-2.5-flash",
    # Krav-lager
    "hotmodelleraren":   "google/gemini-2.5-flash",
    "dataskyddsjuristen": "google/gemini-2.5-flash",
    # Specialists: Gemini 2.5 Flash — strong reasoning + reliable JSON, ~85% cheaper than Sonnet
    "architecture":    "google/gemini-2.5-flash",
    "integration":     "google/gemini-2.5-flash",
    "risk":            "google/gemini-2.5-flash",
    "ux":              "google/gemini-2.5-flash",
    "ui_design":       "google/gemini-2.5-flash",
    "frontend":        "google/gemini-2.5-flash",
    "responsive":      "google/gemini-2.5-flash",
    "accessibility":   "google/gemini-2.5-flash",
    "database":        "google/gemini-2.5-flash-lite",  # checklist task
    "datamigration":   "google/gemini-2.5-flash",
    "api":             "google/gemini-2.5-flash",
    "error_handling":  "google/gemini-2.5-flash",
    "edge_case":       "google/gemini-2.5-flash",
    "code_quality":    "google/gemini-2.5-flash-lite",  # style/DRY pass
    "security":        "google/gemini-2.5-flash",
    "hemlighetsvakten": "google/gemini-2.5-flash",
    "performance":     "google/gemini-2.5-flash",
    "scalability":     "google/gemini-2.5-flash",
    "data_privacy":    "google/gemini-2.5-flash",
    "testing":         "google/gemini-2.5-flash",
    # Multimodal (vision) — Gemini 2.5 Flash: also multimodal, fast, reliable JSON.
    # (2.5 Pro burned its budget on reasoning prose → parse failures + timeouts in E2E.)
    "visual_qa":       "google/gemini-2.5-flash",
    "rotorsak":        "google/gemini-2.5-flash",
    # Backlog grooming — structuring task, Gemini Flash is fast + reliable JSON
    "backloghallaren": "google/gemini-2.5-flash",
    # Final user-facing spec — Sonnet as quality anchor + vendor hedge
    "prompt_smith":    "anthropic/claude-sonnet-4.6",
    # Simple evaluation / translation
    "completeness":    "google/gemini-2.5-flash-lite",
    "bestallarsammanfattaren": "google/gemini-2.5-flash",
}

_settings_cache = {"mtime": None, "data": None}

def load_settings() -> dict:
    """mtime-cached settings read — called dozens of times per review run."""
    if SETTINGS_FILE.exists():
        try:
            mtime = SETTINGS_FILE.stat().st_mtime
            if _settings_cache["mtime"] == mtime and _settings_cache["data"] is not None:
                return dict(_settings_cache["data"])  # copy — callers mutate (key masking)
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            _settings_cache.update(mtime=mtime, data=data)
            return dict(data)
        except Exception:
            pass
    return {
        "api_key": "", "model": "claude-sonnet-4-6",
        "openrouter_key": "",
        "agent_models": {},
        "supabase_url": "", "supabase_key": "",
        "github_token": "", "self_repo": "", "self_branch": "main",
    }


def save_settings(s: dict):
    with _settings_lock:
        # Atomic write — write to temp then replace, prevents corruption on crash
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)


def get_client():
    """Returns Anthropic client for direct API calls (fallback only)."""
    key = load_settings().get("api_key", "")
    if not key:
        return None
    return anthropic.Anthropic(api_key=key, timeout=120.0)


_or_client_cache = {"key": None, "client": None}
_or_client_lock = threading.Lock()

def get_openrouter_client():
    """Returns OpenRouter client (primary provider). Cached — reuses HTTP connection pool
    across all agent calls instead of building a new client per call."""
    key = load_settings().get("openrouter_key", "").strip()
    if not key:
        return None
    with _or_client_lock:
        if _or_client_cache["key"] == key and _or_client_cache["client"] is not None:
            return _or_client_cache["client"]
        import openai as _openai
        client = _openai.OpenAI(
            api_key=key,
            base_url="https://openrouter.ai/api/v1",
            timeout=80.0,  # must stay below the 95s per-agent budget so our retry can fire
            max_retries=0,  # we do our own retry with smarter classification
            default_headers={
                "HTTP-Referer": "https://prompt-team.local",
                "X-Title": "Prompt Team",
            }
        )
        _or_client_cache.update(key=key, client=client)
        return client


_TRANSIENT_MARKERS = ("429", "500", "502", "503", "504", "overloaded", "timeout", "timed out",
                      "connection", "temporarily", "rate limit")

# $/1M tokens (input, output) — for per-run cost reporting. Unknown models → tokens only.
_MODEL_PRICES = {
    "google/gemini-2.5-flash":        (0.30, 2.50),
    "google/gemini-2.5-flash-lite":   (0.10, 0.40),
    "google/gemini-2.5-pro":          (1.25, 10.00),
    "anthropic/claude-sonnet-4.6":    (3.00, 15.00),
    "anthropic/claude-opus-4.8":      (5.00, 25.00),
    "anthropic/claude-haiku-4.5":     (1.00, 5.00),
    "openai/gpt-4o":                  (2.50, 10.00),
    "openai/o3":                      (2.00, 8.00),
    "openai/o4-mini":                 (1.10, 4.40),
    "deepseek/deepseek-r1-0528":      (0.50, 2.15),
    "deepseek/deepseek-chat-v3-0324": (0.20, 0.77),
    "x-ai/grok-4.20":                 (1.25, 2.50),
    "meta-llama/llama-4-maverick":    (0.15, 0.60),
}

def _cost_usd(model: str, tok_in: int, tok_out: int):
    p = _MODEL_PRICES.get(model)
    if not p:
        return None
    return (tok_in * p[0] + tok_out * p[1]) / 1_000_000


def _or_chat(model: str, messages: list, max_tokens: int, want_json: bool = True,
             usage_out: list = None) -> str:
    """Single hardened OpenRouter chat call.
    - response_format json_object when want_json (eliminates prose-instead-of-JSON failures)
    - falls back without response_format if the provider rejects it
    - retries transient errors (429/5xx/connection) with backoff
    - appends {model, tokens_in, tokens_out, cost_usd} to usage_out if given"""
    or_client = get_openrouter_client()
    if not or_client:
        raise RuntimeError("OpenRouter-nyckel saknas i inställningar")

    def _once(use_rf: bool) -> str:
        kwargs = dict(model=model, max_tokens=max_tokens, messages=messages)
        if use_rf:
            kwargs["response_format"] = {"type": "json_object"}
        resp = or_client.chat.completions.create(**kwargs)
        if usage_out is not None and getattr(resp, "usage", None):
            ti = resp.usage.prompt_tokens or 0
            to = resp.usage.completion_tokens or 0
            usage_out.append({"model": model, "tokens_in": ti, "tokens_out": to,
                              "cost_usd": _cost_usd(model, ti, to)})
        return (resp.choices[0].message.content or "") if resp.choices else ""

    use_rf = want_json
    last_err = None
    for attempt in range(3):
        try:
            return _once(use_rf)
        except Exception as e:
            msg = str(e).lower()
            last_err = e
            # Provider rejects response_format → drop it and retry immediately
            if use_rf and ("response_format" in msg or "json_object" in msg or "invalid_request" in msg):
                logger.info("[or_chat] %s rejected response_format, retrying without", model)
                use_rf = False
                continue
            if attempt < 2 and any(m in msg for m in _TRANSIENT_MARKERS):
                wait = 1.5 * (attempt + 1)
                logger.warning("[or_chat] transient error from %s (%s), retry in %.1fs", model, str(e)[:80], wait)
                import time as _time
                _time.sleep(wait)
                continue
            raise
    raise last_err


# All models go through OpenRouter (provider prefix in model ID)
# Only bare model names without "/" fall back to direct Anthropic
def _is_openrouter_model(model: str) -> bool:
    return "/" in model


def get_agent_model(agent_id: str, fallback: str) -> str:
    """Resolve the model for an agent: user override > curated default > agent dict fallback."""
    s = load_settings()
    agent_models = s.get("agent_models", {})
    return agent_models.get(agent_id) or _DEFAULT_AGENT_MODELS.get(agent_id) or fallback


# ──────────────────────────────────────────────
# BACKLOG STORAGE — the backbone of the "Granska kod" loop
# ──────────────────────────────────────────────
# A backlog item is a deduplicated, prioritized finding that can become the
# seed of one buildable spec. Groomed by Backloghållaren, persisted here.
#   { id, project_id, session_id, title, priority P0|P1|P2,
#     status öppen|pågår|åtgärdad|återkommit, source_agents[], finding,
#     suggestion, effort S|M|L, iteration, created_at, updated_at }

BACKLOG_FILE = BASE_DIR / "backlog.json"
_backlog_lock = threading.Lock()
VALID_PRIORITIES = ("P0", "P1", "P2")
VALID_STATUSES = ("öppen", "pågår", "åtgärdad", "återkommit")

def _backlog_load() -> list:
    if BACKLOG_FILE.exists():
        try:
            data = json.loads(BACKLOG_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error("backlog.json corrupt (%s) — returning empty; not overwriting until next save.", e)
    return []

_SV_STOPWORDS = {"i", "på", "för", "till", "och", "att", "en", "ett", "med", "av", "som", "den",
                 "det", "the", "a", "an", "in", "of", "to", "and", "for", "with", "is", "via"}

def _sig_tokens(it: dict) -> set:
    """Significant tokens from a backlog item's title + finding, prefix-stemmed to 6 chars
    so Swedish inflections match (konkatenering/konkateneras → 'konkat')."""
    text = f"{it.get('title','')} {it.get('finding','')}".lower()
    raw = re.findall(r"[a-zåäö0-9_]{3,}", text)
    return {t[:6] for t in raw if t not in _SV_STOPWORDS}

def _is_same_issue(a_tokens: set, b_tokens: set) -> bool:
    """Overlap fallback — primary regression matching is done semantically by Backloghållaren."""
    if not a_tokens or not b_tokens:
        return False
    inter = len(a_tokens & b_tokens)
    return inter / min(len(a_tokens), len(b_tokens)) >= 0.5

def backlog_add_items(new_items: list, project_id: str, session_id: str) -> list:
    """Append groomed backlog items with dedup + regression detection.
    - New finding fuzzy-matches an 'åtgärdad' item   → status 'återkommit' (regression!)
    - New finding fuzzy-matches an open/pågår item   → skip (already tracked, no duplicate)
    All under the lock — load+modify+save is atomic vs concurrent reviews."""
    now = datetime.now().isoformat(timespec="seconds")
    with _backlog_lock:
        items = _backlog_load()
        proj = [i for i in items if i.get("project_id") == project_id]
        resolved = [(_sig_tokens(i), i) for i in proj if i.get("status") == "åtgärdad"]
        tracked = [(_sig_tokens(i), i) for i in proj if i.get("status") in ("öppen", "pågår", "återkommit")]
        iteration = 1 + max([i.get("iteration", 0) for i in proj] or [0])
        for it in new_items:
            title = (it.get("title") or it.get("finding") or "Namnlös").strip()[:200]
            prio = it.get("priority") if it.get("priority") in VALID_PRIORITIES else "P2"
            new_tokens = _sig_tokens({"title": title, "finding": it.get("finding", "")})
            # Already tracked as open? Don't duplicate — bump updated_at instead.
            existing = next((i for tok, i in tracked if _is_same_issue(new_tokens, tok)), None)
            if existing:
                existing["updated_at"] = now
                continue
            # Previously fixed? That's a regression — LLM semantic flag first, fuzzy fallback.
            regressed = bool(it.get("regression")) or any(
                _is_same_issue(new_tokens, tok) for tok, _ in resolved)
            items.append({
                "id": str(uuid.uuid4()),
                "project_id": project_id,
                "session_id": session_id,
                "title": title,
                "priority": prio,
                "status": "återkommit" if regressed else "öppen",
                "source_agents": it.get("source_agents", []),
                "finding": it.get("finding", title),
                "suggestion": it.get("suggestion", ""),
                "effort": it.get("effort") if it.get("effort") in ("S", "M", "L") else "M",
                "iteration": iteration,
                "created_at": now,
                "updated_at": now,
            })
        tmp = BACKLOG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(BACKLOG_FILE)
    return [i for i in items if i.get("project_id") == project_id]

def _norm(s: str) -> str:
    return " ".join(str(s).lower().split())


# ──────────────────────────────────────────────
# BUILD QUEUE — byggkön: specs in logical order, builder-ready
# ──────────────────────────────────────────────
# Status lifecycle (4 states a non-coder understands):
#   kö → byggs → klar | behover_dig → byggs (resend) ...
# WIP limit: max 1 'byggs' per project — makes the order real.
# The builder contract: /send returns a `job` object; today a human copies
# spec_markdown, tomorrow a webhook/CLI adapter POSTs the same job and calls
# /result + /review. Zero refactoring needed to plug a builder in.

BUILD_QUEUE_FILE = BASE_DIR / "build_queue.json"
BUILD_RESULTS_DIR = BASE_DIR / "build_results"
_queue_lock = threading.Lock()
QUEUE_STATUSES = ("kö", "byggs", "behover_dig", "klar")

def _queue_load() -> list:
    if BUILD_QUEUE_FILE.exists():
        try:
            data = json.loads(BUILD_QUEUE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error("build_queue.json corrupt (%s) — returning empty; not overwriting.", e)
    return []

def _queue_write(items: list) -> None:
    """Caller must hold _queue_lock."""
    tmp = BUILD_QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(BUILD_QUEUE_FILE)

def _queue_log(item: dict, event: str, detail: str = ""):
    item.setdefault("log", []).append({
        "at": datetime.now().isoformat(timespec="seconds"), "event": event, "detail": detail[:300]})
    item["updated_at"] = datetime.now().isoformat(timespec="seconds")

def queue_create_item(project_id: str, title: str, spec_markdown: str,
                      spec_bestallare: str = "", source: dict = None) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    with _queue_lock:
        items = _queue_load()
        proj_positions = [i.get("position", 0) for i in items
                          if i.get("project_id") == project_id and not i.get("deleted_at")]
        item = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "title": (title or "Namnlös spec").strip()[:200],
            "spec_markdown": spec_markdown,
            "spec_bestallare": spec_bestallare or "",
            "position": (max(proj_positions) + 10) if proj_positions else 10,
            "status": "kö",
            "source": source or {"type": "manuell"},
            "byggsatt_used": None,
            "attempt_nr": 0,
            "sent_at": None,
            "result_ref": None,
            "result_summary": {},
            "review_started_at": None,
            "last_verdict": {},
            "log": [],
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        _queue_log(item, "skapad", source.get("type") if source else "manuell")
        items.append(item)
        _queue_write(items)
    return item


@app.get("/api/build-queue")
async def get_build_queue(project_id: str = ""):
    items = _queue_load()
    if project_id:
        items = [i for i in items if i.get("project_id") == project_id]
    items = [i for i in items if not i.get("deleted_at")]
    items.sort(key=lambda i: i.get("position", 0))
    return {"items": items}


@app.post("/api/build-queue")
async def post_build_queue(payload: dict):
    spec = (payload.get("spec_markdown") or "").strip()
    if not spec:
        return JSONResponse({"error": "spec_markdown krävs."}, status_code=400)
    item = queue_create_item(
        payload.get("project_id", ""),
        payload.get("title", ""),
        spec,
        payload.get("spec_bestallare", ""),
        payload.get("source") or {"type": "manuell"},
    )
    return {"ok": True, "item": item}


@app.patch("/api/build-queue/{item_id}")
async def patch_build_queue(item_id: str, payload: dict):
    with _queue_lock:
        items = _queue_load()
        item = next((i for i in items if i.get("id") == item_id), None)
        if not item:
            return JSONResponse({"error": "Item hittades inte."}, status_code=404)
        if "status" in payload:
            if payload["status"] not in QUEUE_STATUSES:
                return JSONResponse({"error": f"Ogiltig status. Tillåtna: {', '.join(QUEUE_STATUSES)}"}, status_code=400)
            item["status"] = payload["status"]
            _queue_log(item, "status_override", payload["status"])
        if "title" in payload:
            item["title"] = str(payload["title"]).strip()[:200]
        if "spec_markdown" in payload:
            item["spec_markdown"] = payload["spec_markdown"]
        if payload.get("deleted"):
            item["deleted_at"] = datetime.now().isoformat(timespec="seconds")
            _queue_log(item, "borttagen")
        _queue_write(items)
    return {"ok": True, "item": item}


@app.post("/api/build-queue/reorder")
async def reorder_build_queue(payload: dict):
    project_id = payload.get("project_id", "")
    ordered_ids = payload.get("ordered_ids") or []
    with _queue_lock:
        items = _queue_load()
        proj_ids = {i["id"] for i in items if i.get("project_id") == project_id and not i.get("deleted_at")}
        if set(ordered_ids) != proj_ids:
            return JSONResponse({"error": "ordered_ids matchar inte köns innehåll."}, status_code=400)
        pos = {iid: (n + 1) * 10 for n, iid in enumerate(ordered_ids)}
        for i in items:
            if i["id"] in pos:
                i["position"] = pos[i["id"]]
                i["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _queue_write(items)
    return {"ok": True}


@app.post("/api/build-queue/{item_id}/send")
async def send_build_queue_item(item_id: str, payload: dict):
    """kö|behover_dig → byggs. Returns the builder `job` contract.
    Today: human copies job.spec_markdown. Tomorrow: an adapter POSTs job to a builder."""
    byggsatt = payload.get("byggsatt") or {}
    profile = payload.get("profile") or {}
    with _queue_lock:
        items = _queue_load()
        item = next((i for i in items if i.get("id") == item_id and not i.get("deleted_at")), None)
        if not item:
            return JSONResponse({"error": "Item hittades inte."}, status_code=404)
        if item["status"] not in ("kö", "behover_dig"):
            return JSONResponse({"error": f"Kan inte skicka i status '{item['status']}'."}, status_code=409)
        # WIP limit: one build at a time per project keeps the order real
        busy = next((i for i in items if i.get("project_id") == item["project_id"]
                     and i.get("status") == "byggs" and not i.get("deleted_at")), None)
        if busy:
            return JSONResponse({"error": f"Ett bygge pågår redan: '{busy['title']}'. Slutför det först.",
                                 "busy_item_id": busy["id"]}, status_code=409)
        item["attempt_nr"] = item.get("attempt_nr", 0) + 1
        item["status"] = "byggs"
        item["sent_at"] = datetime.now().isoformat(timespec="seconds")
        item["byggsatt_used"] = byggsatt or None
        _queue_log(item, "skickad", f"försök {item['attempt_nr']}")
        _queue_write(items)

    feedback = ""
    lv = item.get("last_verdict") or {}
    if lv.get("kvarstaende"):
        feedback = "FÖREGÅENDE FÖRSÖK UNDERKÄNDES. Kvarstående problem:\n" + \
                   "\n".join(f"- {k}" for k in lv["kvarstaende"][:10])

    job = {
        "queue_item_id": item["id"],
        "attempt_nr": item["attempt_nr"],
        "project_id": item["project_id"],
        "title": item["title"],
        "spec_markdown": item["spec_markdown"],
        "feedback": feedback,
        "byggsatt": item.get("byggsatt_used") or {},
        "project_context": build_project_context(profile),
        "repo": {"name": profile.get("repo", ""), "branch": profile.get("branch", "main")},
        "callback": {
            "result": f"/api/build-queue/{item['id']}/result",
            "review": f"/api/build-queue/{item['id']}/review",
        },
    }
    return {"ok": True, "status": "byggs", "job": job}


@app.post("/api/build-queue/{item_id}/result")
async def build_queue_result(item_id: str, payload: dict):
    """Builder (or human) reports the build output. Idempotent per attempt.
    Never runs review inline — call /review for that."""
    with _queue_lock:
        items = _queue_load()
        item = next((i for i in items if i.get("id") == item_id and not i.get("deleted_at")), None)
        if not item:
            return JSONResponse({"error": "Item hittades inte."}, status_code=404)
        if item["status"] != "byggs":
            return JSONResponse({"error": f"Resultat accepteras bara i status 'byggs' (nu: {item['status']})."}, status_code=409)
        attempt = payload.get("attempt_nr", item.get("attempt_nr"))
        if attempt != item.get("attempt_nr"):
            return JSONResponse({"error": "attempt_nr matchar inte aktuellt försök."}, status_code=409)
        if item.get("result_ref") and str(item["result_ref"]).endswith(f"_{attempt}.json"):
            return {"ok": True, "duplicate": True}
        BUILD_RESULTS_DIR.mkdir(exist_ok=True)
        ref = f"{item_id}_{attempt}.json"
        (BUILD_RESULTS_DIR / ref).write_text(json.dumps({
            "code": payload.get("code", ""),
            "diff": payload.get("diff", ""),
            "files": payload.get("files", []),
            "log": payload.get("log", ""),
        }, ensure_ascii=False), encoding="utf-8")
        item["result_ref"] = ref
        item["result_summary"] = {
            "received_at": datetime.now().isoformat(timespec="seconds"),
            "commit_sha": payload.get("commit_sha"),
            "builder_meta": payload.get("builder_meta"),
            "build_status": payload.get("status", "byggd"),
        }
        _queue_log(item, "resultat", payload.get("status", "byggd"))
        _queue_write(items)
    return {"ok": True}


@app.post("/api/build-queue/advance")
async def advance_build_queue(project_id: str = ""):
    """Next buildable item per position, if nothing is building.
    Drives the 'Bygg nästa' button today; the auto-dispatch hook tomorrow."""
    items = [i for i in _queue_load()
             if i.get("project_id") == project_id and not i.get("deleted_at")]
    if any(i.get("status") == "byggs" for i in items):
        return {"next_item": None, "reason": "Ett bygge pågår redan."}
    queued = sorted([i for i in items if i.get("status") == "kö"],
                    key=lambda i: i.get("position", 0))
    return {"next_item": queued[0] if queued else None}


# ──────────────────────────────────────────────
# SESSION STORAGE (lokal JSON + Supabase fallback)
# ──────────────────────────────────────────────

LOCAL_SESSIONS_FILE = BASE_DIR / "sessions.json"
_sessions_lock = threading.Lock()

def _local_load() -> dict:
    """Load all sessions from local JSON file. Returns {} on missing or corrupt file."""
    if LOCAL_SESSIONS_FILE.exists():
        try:
            return json.loads(LOCAL_SESSIONS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("sessions.json is corrupt or unreadable (%s) — returning empty dict; "
                         "file will NOT be overwritten until next explicit save.", e)
    return {}

def _local_save(data: dict):
    """Atomic-safe write: holds lock across load→modify→write to prevent lost-update races."""
    with _sessions_lock:
        LOCAL_SESSIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _atomic_write(data: dict) -> None:
    """Write dict to sessions.json via a temp file — safe against mid-write crashes."""
    tmp = LOCAL_SESSIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LOCAL_SESSIONS_FILE)

def _local_update(session_id: str, payload: dict) -> None:
    """Thread-safe read-modify-write for a single session entry."""
    with _sessions_lock:
        if LOCAL_SESSIONS_FILE.exists():
            try:
                data = json.loads(LOCAL_SESSIONS_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("sessions.json corrupt during update (%s) — aborting save to avoid data loss.", e)
                return
        else:
            data = {}
        data[session_id] = payload
        _atomic_write(data)

def _local_delete(session_id: str) -> bool:
    """Thread-safe read-modify-write for deletion. Returns True if key existed."""
    with _sessions_lock:
        if LOCAL_SESSIONS_FILE.exists():
            try:
                data = json.loads(LOCAL_SESSIONS_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("sessions.json corrupt during delete (%s) — aborting.", e)
                return False
        else:
            data = {}
        existed = session_id in data
        if existed:
            data.pop(session_id)
            _atomic_write(data)
        return existed

def _sb_headers() -> dict | None:
    s = load_settings()
    url = s.get("supabase_url", "").strip().rstrip("/")
    key = s.get("supabase_key", "").strip()
    if not url or not key:
        return None
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def _sb_base() -> str:
    """Normalised Supabase base URL. Tolerates users pasting either the bare
    project URL (https://xxx.supabase.co) OR the full REST endpoint (…/rest/v1),
    so we never end up with a doubled /rest/v1 path."""
    base = load_settings().get("supabase_url", "").strip().rstrip("/")
    if base.lower().endswith("/rest/v1"):
        base = base[: -len("/rest/v1")]
    return base

def _sb_url(path: str) -> str:
    return f"{_sb_base()}/rest/v1/{path}"


# Latest migration version defined in supabase_setup.sql. Bump when you append a
# new migration block there. The /api/health check reads the connected DB's
# schema_migrations table and warns if it's behind this number.
SUPABASE_SCHEMA_VERSION = 2

def check_supabase_schema() -> dict:
    """Read the applied schema version from Supabase via REST (no DDL — read-only).
    Returns {ok, current, expected, msg}. Surfaces schema drift without a Postgres
    connection: PostgREST can't run DDL, so migrations stay manual, but we CAN read
    the schema_migrations ledger to tell the user if supabase_setup.sql needs re-running."""
    headers = _sb_headers()
    if not headers:
        return {"ok": False, "current": None, "expected": SUPABASE_SCHEMA_VERSION, "msg": "Supabase ej konfigurerad"}
    try:
        r = httpx.get(_sb_url("schema_migrations?select=version&order=version.desc&limit=1"),
                      headers=headers, timeout=8.0)
        if r.status_code == 404 or (r.status_code == 400 and "schema_migrations" in r.text):
            return {"ok": False, "current": 0, "expected": SUPABASE_SCHEMA_VERSION,
                    "msg": "schema_migrations saknas — kör supabase_setup.sql i Supabase SQL Editor"}
        if r.status_code != 200:
            return {"ok": False, "current": None, "expected": SUPABASE_SCHEMA_VERSION,
                    "msg": f"Kunde inte läsa schemaversion (HTTP {r.status_code})"}
        rows = r.json()
        current = rows[0]["version"] if rows else 0
        if current < SUPABASE_SCHEMA_VERSION:
            return {"ok": False, "current": current, "expected": SUPABASE_SCHEMA_VERSION,
                    "msg": f"Schema ligger efter (v{current}, behöver v{SUPABASE_SCHEMA_VERSION}) — kör om supabase_setup.sql"}
        return {"ok": True, "current": current, "expected": SUPABASE_SCHEMA_VERSION,
                "msg": f"Schema v{current} ✓"}
    except Exception as e:
        return {"ok": False, "current": None, "expected": SUPABASE_SCHEMA_VERSION, "msg": str(e)[:80]}

def _sb_available() -> bool:
    """Quick DNS check — only try Supabase if hostname resolves."""
    import socket
    s = load_settings()
    url = s.get("supabase_url", "").strip()
    if not url or not s.get("supabase_key", "").strip():
        return False
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(3)
        try:
            socket.getaddrinfo(host, 443)
        finally:
            socket.setdefaulttimeout(old_timeout)
        return True
    except Exception:
        return False

def _migrate_sessions() -> None:
    """One-time migration: backfill project_id='' on sessions that predate the field."""
    if not LOCAL_SESSIONS_FILE.exists():
        return
    try:
        with _sessions_lock:
            data = json.loads(LOCAL_SESSIONS_FILE.read_text(encoding="utf-8"))
            dirty = False
            for v in data.values():
                if "project_id" not in v:
                    v["project_id"] = ""
                    dirty = True
            if dirty:
                _atomic_write(data)
                logger.info("Migrated %d sessions to include project_id field", sum(1 for v in data.values() if v.get("project_id") == ""))
    except Exception as e:
        logger.warning("Session migration failed (non-critical): %s", e)

def auto_name(input_text: str) -> str:
    words = input_text.strip().split()[:7]
    name = " ".join(words)
    if len(name) > 60:
        name = name[:57] + "..."
    date_str = datetime.now().strftime("%d %b")
    return f"{name} · {date_str}"

def save_session(session_id: str, name: str, mode: str, input_text: str,
                 context: str, results: list, smith: dict, stats: dict,
                 project_id: str = "") -> dict:
    """Returns {"local": bool, "cloud": bool} so callers know what succeeded."""
    now = datetime.now().isoformat()
    payload = {
        "id": session_id, "name": name, "mode": mode,
        "created_at": now, "input_text": input_text,
        "context": context, "results": results, "smith": smith, "stats": stats,
        "project_id": project_id,
    }
    local_ok = False
    cloud_ok = False

    # Always save locally first (instant, reliable, race-safe)
    try:
        _local_update(session_id, payload)
        local_ok = True
    except Exception as e:
        logger.warning("Local session save failed: %s", e)

    # Try Supabase if configured and reachable
    if _sb_available():
        try:
            headers = _sb_headers()
            r = httpx.post(
                _sb_url("prompt_sessions"), json=payload,
                headers={**headers, "Prefer": "resolution=merge-duplicates,return=minimal"},
                timeout=10.0
            )
            if r.status_code in (200, 201):
                cloud_ok = True
                logger.info("Session saved to Supabase")
            else:
                logger.warning("Supabase save returned %s: %s", r.status_code, r.text[:120])
        except Exception as e:
            logger.warning("Supabase save failed (local backup exists): %s", e)

    return {"local": local_ok, "cloud": cloud_ok}

def list_sessions(project_id: str = "") -> list:
    # Fall back to local (Supabase DNS unreliable)
    try:
        data = _local_load()
        def _matches(v):
            if not project_id:
                return True
            vid = v.get("project_id", "")
            # Backward compat: old sessions without project_id show under "main"
            if project_id == "main" and not vid:
                return True
            return vid == project_id
        sessions = [
            {
                "id": v["id"], "name": v["name"], "mode": v["mode"],
                "created_at": v.get("created_at", ""),
                "project_id": v.get("project_id", ""),
            }
            for v in data.values()
            if _matches(v)
        ]
        sessions.sort(key=lambda x: x["created_at"], reverse=True)
        return sessions[:50]
    except Exception:
        return []

def get_session(session_id: str) -> dict | None:
    # Local first — it already has the data and answers in ~1ms.
    # Supabase only as recovery for sessions missing locally (e.g. other machine).
    try:
        data = _local_load()
        if session_id in data:
            return data[session_id]
    except Exception:
        pass
    if _sb_available():
        try:
            headers = _sb_headers()
            r = httpx.get(
                _sb_url(f"prompt_sessions?id=eq.{session_id}&select=*"),
                headers=headers, timeout=10.0
            )
            if r.status_code == 200:
                rows = r.json()
                return rows[0] if rows else None
        except Exception as e:
            logger.warning("Supabase get failed: %s", e)
    return None

def delete_session(session_id: str) -> bool:
    # Delete locally (race-safe)
    local_ok = False
    try:
        local_ok = _local_delete(session_id)
    except Exception as e:
        logger.warning("Local delete failed: %s", e)
    # Try Supabase too
    if _sb_available():
        try:
            headers = _sb_headers()
            httpx.delete(_sb_url(f"prompt_sessions?id=eq.{session_id}"), headers=headers, timeout=10.0)
        except Exception:
            pass
    return local_ok


# ──────────────────────────────────────────────
# AGENT DEFINITIONS
# ──────────────────────────────────────────────

_SEVERITY_GUIDE = (
    " Severity: HIGH=kritisk/måste åtgärdas, MEDIUM=bör åtgärdas, LOW=rekommendation."
    " Severity sätts efter ditt ALLVARLIGASTE fynd — inte genomsnittet."
    " En enda bekräftad injection, trasig auth eller exponerad hemlighet ⇒ HIGH."
    " Om inga verkliga problem hittas: returnera status GODKÄND med tomma listor."
    " Returnera ENBART JSON: "
    '{"status":"GODKÄND"|"UNDERKÄND","findings":["konket problem..."],"severity":"LOW"|"MEDIUM"|"HIGH","suggestions":["åtgärd..."]}'
)

# Mode constants — every specialist agent declares which modes it runs in.
M_NY = "ny_funktion"       # idé → spec
M_GRANSKA = "granska_kod"  # befintlig kod → fynd → backlog → loop
M_BUGG = "buggrapport"     # symptom + kod/skärmdump → rotorsak → fix-spec

# ──────────────────────────────────────────────
# SPECIALIST AGENTS — flat list, each tagged with modes/layer.
# Run in parallel after Kravanalytikern. Filtered per mode at request time.
# ──────────────────────────────────────────────
SPECIALIST_AGENTS = [
    # ── Krav-lager (pre-build kravgenererande granskare) ──
    {
        "id": "hotmodelleraren",
        "name": "Hotmodelleraren",
        "emoji": "🎯",
        "phase": "pre", "layer": "krav",
        "modes": [M_NY, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är säkerhetsarkitekt som gör threat modeling INNAN bygget. Du föreslår säkerhetskrav, inte buggar i färdig kod.\n"
            "Analysera idén/funktionen och identifiera:\n"
            "• Trust boundaries — var korsar data en gräns mellan betrodd/obetrodd zon?\n"
            "• Abuse cases — hur kan en illvillig användare missbruka funktionen?\n"
            "• STRIDE — Spoofing, Tampering, Repudiation, Information disclosure, DoS, Elevation of privilege?\n"
            "• Auth/authz-krav — vilken behörighet krävs och var måste den kontrolleras?\n"
            "• Känslig data — vilka fält behöver kryptering, maskning eller åtkomstkontroll?\n"
            "• Indatakontroll — vilken indata måste valideras/saneras innan användning?\n"
            "Varje finding är ett SÄKERHETSKRAV att bygga in från start. Formulera som 'Kräv: [kontroll] för att förhindra [hot]'."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "dataskyddsjuristen",
        "name": "Dataskyddsjuristen",
        "emoji": "⚖️",
        "phase": "pre", "layer": "krav",
        "modes": [M_NY, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är dataskyddsjurist (GDPR/EU). Du formulerar dataskyddskrav INNAN bygget.\n"
            "Analysera idén och identifiera krav kring:\n"
            "• Personuppgifter — vilka PII samlas in och behandlas?\n"
            "• Rättslig grund — finns laglig grund (samtycke, avtal, berättigat intresse)?\n"
            "• Samtycke — krävs aktivt samtycke och hur återkallas det?\n"
            "• Dataminimering — samlas bara det som verkligen behövs för ändamålet?\n"
            "• Lagringstid (retention) — hur länge sparas data och när raderas den?\n"
            "• Registrerades rättigheter — stöds åtkomst, rättelse, radering, dataportabilitet?\n"
            "• Tredjelandsöverföring — skickas data utanför EU/EES?\n"
            "Om idén inte rör personuppgifter alls: returnera GODKÄND. Formulera findings som GDPR-KRAV."
            + _SEVERITY_GUIDE
        ),
    },
    # ── Arkitektur & system ──
    {
        "id": "architecture",
        "name": "Arkitekten",
        "emoji": "🏗️",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är en erfaren enterprise-arkitekt. Analysera beskrivningen och identifiera konkreta arkitekturrisker.\n"
            "Kontrollera specifikt:\n"
            "• Separation of concerns — blandas domänlogik, UI och datalagring i samma komponent?\n"
            "• Single Responsibility — gör en klass/modul för många saker?\n"
            "• Beroenderiktning — pekar beroenden rätt (in mot kärnan, inte ut)?\n"
            "• Cirkulära beroenden — kan A→B→A uppstå?\n"
            "• Skalningsproblem — håller designen om last 10×?\n"
            "• God object / Blob anti-pattern — ett objekt vet för mycket?\n"
            "• Tight coupling — ändring i A kräver alltid ändring i B?\n"
            "• Rätt mönster — används rätt designmönster för problemet?\n"
            "Formulera varje finding som ett konkret problem, inte en generell observation."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "integration",
        "name": "Integrationsanalytikern",
        "emoji": "🔗",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är integrationsarkitekt. Analysera hur ändringen passar in i det befintliga systemet och vad den kan bryta.\n"
            "Kontrollera specifikt:\n"
            "• Berörda befintliga delar — vilka befintliga moduler/endpoints/databastabeller påverkas?\n"
            "• Nya externa beroenden — vilka API:er, tjänster eller bibliotek tillkommer?\n"
            "• Auth-påverkan — påverkas befintlig autentisering eller behörighetsmodell?\n"
            "• Datamodell-påverkan — kräver det nya schema-ändringar eller migrationer?\n"
            "• Breaking changes — riskerar ändringen att bryta befintlig funktionalitet (regression)?\n"
            "• Deploy-ordning — finns det beroenden mellan delar som kräver specifik deploy-sekvens?\n"
            "• Test-strategi — vilka befintliga tester behöver uppdateras?\n"
            "Rapportera enbart integrationsspecifika problem — upprepa INTE säkerhets- eller kvalitetsfynd "
            "som andra agenter äger, även om du ser dem.\n"
            "Om projektkontext saknas och du inte kan avgöra integrationen: returnera GODKÄND med notering."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "risk",
        "name": "Riskvärderaren",
        "emoji": "⚠️",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är senior riskanalytiker med erfarenhet av IT-projekt. Identifiera konkreta risker i beskrivningen.\n"
            "Kontrollera specifikt:\n"
            "• Tekniska risker — väljs teknologi som är oupprovet, komplex eller har dåligt community-stöd?\n"
            "• Scope creep — är idén så bred att den riskerar att expandera okontrollerat?\n"
            "• Beroenderisker — finns externa tjänster/API:er utan fallback eller SLA?\n"
            "• Säkerhetsrisker — hanteras känslig data (auth, betalning, PII) på ett osäkert sätt?\n"
            "• Prestanda-fallgropar — finns uppenbara flaskhalsar vid förväntad last?\n"
            "• Migrationsrisker — krävs komplicerad datamigration eller breaking changes?\n"
            "• Underskattad komplexitet — verkar delar av idén enklare än de faktiskt är?\n"
            "• Saknande kompetens — kräver idén specialistkompetens som kanske saknas?\n"
            "Formulera varje risk som: 'Risk: [vad] → Konsekvens: [vad händer] → Mitigation: [åtgärd]'."
            + _SEVERITY_GUIDE
        ),
    },
    # ── Design & frontend (den visuella triaden + tillgänglighet) ──
    {
        "id": "ux",
        "name": "UX-agenten",
        "emoji": "🧭",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är senior UX-designer och produktstrateg. Granska FLÖDEN och ANVÄNDBARHET — inte visuell stil (det äger UI/Design-granskaren).\n"
            "Kontrollera specifikt:\n"
            "• Flödeslogik — är stegen för att slutföra uppgiften naturliga och minimala?\n"
            "• Informationsarkitektur — hittar användaren rätt sak på rätt plats?\n"
            "• Loading states — hanteras väntetid med synlig feedback?\n"
            "• Empty states — visas meningsfull text/action när ingen data finns?\n"
            "• Mikrotext/UX-copy — är knapptexter, etiketter och felmeddelanden tydliga och handlingsdrivande?\n"
            "• Felmeddelanden — är de förståeliga för slutanvändare (inga stacktraces)?\n"
            "• Destruktiva actions — finns bekräftelsedialog innan radering/irreversibla steg?\n"
            "• Dead ends — kan användaren fastna utan möjlighet att ta sig tillbaka?\n"
            "• Första-gångs-upplevelse — förstår ny användare vad de ska göra?\n"
            "Formulera varje finding ur användarens perspektiv ('Användaren kan inte förstå...')."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "ui_design",
        "name": "UI/Design-granskaren",
        "emoji": "🎨",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är senior UI- och visuell designgranskare. Granska DESIGNINTENTION och visuell kvalitet i kod/beskrivning (inte flöden — det äger UX-agenten).\n"
            "Kontrollera specifikt:\n"
            "• Design tokens — används CSS-variabler/tokens, eller finns hårdkodade hex-färger?\n"
            "• Typografisk skala — är fontstorlekar från en definierad skala med tydlig hierarki?\n"
            "• Spacing-system — används 4/8px-rutnät konsekvent?\n"
            "• Visuell hierarki — är det tydligt vad som är primär/sekundär action?\n"
            "• Färg & kontrast — uppfyller text/bakgrund WCAG AA (4.5:1 normal, 3:1 stor text)?\n"
            "• Inline-stilar — finns style-attribut som borde vara CSS-klasser?\n"
            "• Dark mode — bryts layout eller kontrast i dark mode?\n"
            "• Motion — finns animationer, och respekteras prefers-reduced-motion?\n"
            "• Designsystem-konsistens — återanvänds komponenter eller återuppfinns knappar/kort?\n"
            "OBS: Om projektet inte använder ett designsystem, fokusera på konsekvens och kontrast."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "frontend",
        "name": "Frontend-agenten",
        "emoji": "🧱",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är senior frontend-arkitekt med djup kunskap om React, Vue och vanilla JS. Granska frontend-KODENS struktur (inte hur den ser ut).\n"
            "Kontrollera specifikt:\n"
            "• Komponentstruktur — är komponenter/moduler fokuserade på en sak (SRP)?\n"
            "• State-ägarskap — är global state minimal och lokalt state föredras när möjligt?\n"
            "• Datahämtning — hanteras fetch/loading/error-tillstånd konsekvent?\n"
            "• DOM-manipulation — undviks direkta DOM-manipulationer utanför ramverkets lifecycle?\n"
            "• Event listener-läckor — rensas addEventListener med removeEventListener vid cleanup?\n"
            "• Props/parametrar — är funktionsparametrar väldefinierade, inga oklara 'options'-objekt?\n"
            "• Lazy loading — laddas tunga moduler/bilder lazy?\n"
            "• XSS-risk — sätts innerHTML från user-input utan sanitering?\n"
            "• Vanilla JS-specifikt: undviks global namespace pollution, används IIFE/modules?\n"
            "OBS: Anpassa granskningen till projektets faktiska teknikstack från projektkontext."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "responsive",
        "name": "Responsivitet & Mobil",
        "emoji": "📐",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är expert på responsiv webb och mobilanpassning. Granska att lösningen fungerar på alla skärmstorlekar.\n"
            "Kontrollera specifikt:\n"
            "• Viewport meta — finns <meta name='viewport' content='width=device-width'>?\n"
            "• Touch targets — är knappar/klickbara ytor minst 44×44px?\n"
            "• Hover-only — finns interaktioner som enbart triggas av hover (fungerar ej på touch)?\n"
            "• Breakpoints — fungerar layout vid 320px, 375px, 768px och 1024px bredd?\n"
            "• Horisontell scroll — uppstår oavsiktlig horisontell scroll?\n"
            "• Textläsbarhet — är minsta textstorlek ≥14px och läsbar utan zoom?\n"
            "• Formulär — har inputs rätt inputmode (tel, email, number, numeric)?\n"
            "• Overflow — används max-width:100% för bilder/media för att hindra overflow?"
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "accessibility",
        "name": "Tillgänglighet",
        "emoji": "♿",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA, M_BUGG],
        "accepts_images": True,  # optional screenshot for contrast assessment
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är WCAG 2.2 AA-expert och tillgänglighetsingenjör. Granska koden (och ev. bifogad skärmdump) för tillgänglighetsproblem.\n"
            "Kontrollera specifikt:\n"
            "• ARIA-labels — har interaktiva element utan synlig text aria-label/aria-labelledby?\n"
            "• Tangentbordsnavigation — kan allt göras utan mus (Tab, Enter, Escape, piltangenter)?\n"
            "• Focus-states — är :focus-visible synlig på alla interaktiva element?\n"
            "• Kontrast — text vs bakgrund ≥4.5:1, UI-komponenter ≥3:1 (bedöm på skärmdump om bifogad)?\n"
            "• Alt-text — har alla bilder med meningsfullt innehåll alt-attribut?\n"
            "• Formulärlabels — är varje input kopplad till ett <label>-element?\n"
            "• Rubrikhierarki — hoppar rubriker från h1 direkt till h3 eller liknande?\n"
            "• Landmarks — används <main>, <nav>, <header>, <footer> korrekt?\n"
            "• Keyboard traps — kan tangentbordsfokus fastna i modaler/widgets utan Escape-väg?\n"
            "• Target size (WCAG 2.2) — är klickytor minst 24×24px?"
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "visual_qa",
        "name": "Visuell QA-granskaren",
        "emoji": "📸",
        "phase": "post", "layer": "specialist",
        "modes": [M_GRANSKA, M_BUGG],
        "needs_visual_input": True,
        "model": "google/gemini-2.5-flash",
        "max_tokens": 2500,
        "timeout_s": 120,
        "system": (
            "Du är visuell QA-granskare. Du får en SKÄRMDUMP av det FAKTISKT BYGGDA gränssnittet och bedömer det renderade resultatet.\n"
            "Du spekulerar ALDRIG om kod du inte ser. Formulera varje finding som: 'På skärmdumpen syns X (förväntat: Y)'.\n"
            "Granska på bilden:\n"
            "• Renderingsdefekter — överlappande element, avklippt text, felaktig wrapping?\n"
            "• Trasiga tillstånd — hängd spinner, tom yta, felbanner, placeholder som inte ersatts?\n"
            "• Visuell hierarki i praktiken — syns primär action tydligt, eller drunknar den?\n"
            "• Spacing & alignment — ojämna marginaler, element som inte ligger i linje?\n"
            "• Kontrast & läsbarhet — text som är svår att läsa mot sin bakgrund?\n"
            "• Responsivt utfall — tecken på att layouten brutits vid denna bredd?\n"
            "• Synlig känslig data — exponeras API-nycklar, tokens, omaskerad PII eller stacktrace på skärmen?\n"
            "  (källnivå-fynd hänvisas till Hemlighetsvakten/Säkerheten — du rapporterar bara vad som SYNS)\n"
            "Om ingen skärmdump finns: returnera GODKÄND."
            + _SEVERITY_GUIDE
        ),
    },
    # ── Backend, data & kontrakt ──
    {
        "id": "database",
        "name": "Databasagenten",
        "emoji": "🗄️",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash-lite",
        "system": (
            "Du är senior databasarkitekt med erfarenhet av PostgreSQL, SQLite och NoSQL. Granska beskrivningen/koden.\n"
            "Kontrollera specifikt:\n"
            "• Normalisering — dupliceras data som borde ligga i separat tabell?\n"
            "• Saknade index — vilka kolumner som används i WHERE/JOIN saknar index?\n"
            "• Foreign key-integritet — finns relationer utan FK-constraints?\n"
            "• Rätt datatyper — text för nummer, varchar utan längdbegränsning, timestamp utan tidszon?\n"
            "• N+1-risk — hämtas poster en-och-en i loop istället för JOIN/IN?\n"
            "• Obegränsade queries — saknas LIMIT på listor som kan växa obegränsat?\n"
            "• Råa SQL-strängar — används string-konkatenering istället för parametriserade queries?\n"
            "Rapportera enbart problem med konkret kodbevis — spekulera inte om index, constraints eller "
            "schema som inte syns i underlaget. Svara på svenska.\n"
            "Om beskrivningen inte involverar databas: returnera GODKÄND."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "datamigration",
        "name": "Datamigrationsarkitekten",
        "emoji": "🔀",
        "phase": "post", "layer": "specialist",
        "modes": [M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är expert på schema-evolution och datamigration UTAN dataförlust eller driftstopp.\n"
            "Kontrollera specifikt:\n"
            "• Expand-contract — görs schemaändringar bakåtkompatibelt (lägg till → migrera → ta bort)?\n"
            "• Backfill — finns plan att fylla nya kolumner för befintliga rader?\n"
            "• Rollback — går migrationen att rulla tillbaka säkert om något går fel?\n"
            "• Idempotens — kan migrationen köras om utan att skapa dubbletter eller fel?\n"
            "• Lås & låstid — låses stora tabeller på ett sätt som orsakar driftstopp?\n"
            "• Dataförlust-risk — tas kolumner/tabeller bort innan all data migrerats?\n"
            "• Dual-write/konsistens — om data skrivs till två ställen, hur hålls de i synk?\n"
            "Om ingen schemaändring är inblandad: returnera GODKÄND — rapportera ALDRIG fynd från andra "
            "domäner (säkerhet, kodkvalitet, prestanda); de ägs av andra agenter."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "api",
        "name": "API-agenten",
        "emoji": "📜",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är API-designexpert (REST, GraphQL, RPC). Granska API-design OCH datakontrakt.\n"
            "Kontrollera specifikt:\n"
            "• Datakontrakt — är request/response-shapes explicit definierade (fält, typer, nullbarhet)?\n"
            "• Felkuvert — har alla felresponser samma struktur ({error, code, ...})?\n"
            "• RESTful namngivning — substantiv i plural (GET /users, inte GET /getUser)?\n"
            "• HTTP-metoder — används GET/POST/PUT/PATCH/DELETE semantiskt korrekt?\n"
            "• Statuskoder — returneras rätt koder (201, 400, 404, 409 Conflict)?\n"
            "• Auth-täckning — kräver alla endpoints som hanterar känslig data autentisering?\n"
            "• Dataläckage — returneras fält (lösenord, interna ID:n) som aldrig borde exponeras?\n"
            "• Paginering — kan list-endpoints returnera obegränsat med poster?\n"
            "• Rate limiting & versionering — finns skydd mot burst och strategi för breaking changes?"
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "error_handling",
        "name": "Felhantering",
        "emoji": "🧯",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är robusthets-, felhanterings- och observability-expert. Granska hur fel hanteras och hur systemet kan felsökas i drift.\n"
            "Kontrollera specifikt:\n"
            "• Ohanterade promise rejections — finns async-anrop utan .catch() eller try/catch?\n"
            "• Tysta fel — swallowas exceptions med tom catch-block (catch(e) {})?\n"
            "• Stacktrace-läckage — skickas interna feldetaljer/stacktraces till klienten?\n"
            "• Användarmeddelanden — är felmeddelanden förståeliga utan teknisk jargong?\n"
            "• Timeout & retry — finns timeout på externa anrop och retry på transienta fel?\n"
            "• Finally-block — stängs resurser (DB-connections, file handles) i finally-block?\n"
            "• Observability — finns strukturerad loggning och correlation-ID för att spåra ett request genom systemet?\n"
            "• Graceful degradation — fortsätter applikationen fungera delvis vid komponent-fel?"
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "edge_case",
        "name": "Edge-case-jägaren",
        "emoji": "🪤",
        "phase": "pre", "layer": "specialist",
        "modes": [M_NY, M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är adversariell QA-tänkare. Din uppgift är att hitta edge cases och felvägar som lätt missas.\n"
            "Tänk systematiskt kring:\n"
            "• Tomma värden — tom lista, tom sträng, null, undefined, 0, false?\n"
            "• Gränsvärden — max/min, off-by-one, mycket långa strängar, mycket stora tal?\n"
            "• Samtidighet — vad händer om två användare gör samma sak samtidigt (race conditions)?\n"
            "• Tillståndslivscykel — kan ett objekt hamna i ett ogiltigt mellantillstånd?\n"
            "• Nätverksfel — vad händer vid timeout, avbrott, dubbla anrop, långsam uppkoppling?\n"
            "• Ovanlig indata — emojis, specialtecken, andra tidszoner/locale, klistrad text?\n"
            "• Återanvändning — vad händer andra gången, efter logout, efter sessionsslut?\n"
            "Formulera varje finding som ett konkret scenario: 'Om användaren gör X när Y, så händer Z'."
            + _SEVERITY_GUIDE
        ),
    },
    # ── Kvalitet, säkerhet & drift (granska/bugg) ──
    {
        "id": "code_quality",
        "name": "Kodkvalitet",
        "emoji": "📋",
        "phase": "post", "layer": "specialist",
        "modes": [M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash-lite",
        "system": (
            "Du är senior kodkvalitets-granskare. Granska kodstil, läsbarhet och duplicering — inte logik eller säkerhet.\n"
            "Kontrollera specifikt:\n"
            "• Namngivning — är variabel-/funktionsnamn beskrivande och utan förkortningar?\n"
            "• Konvention — följs camelCase i JS/TS, snake_case i Python konsekvent?\n"
            "• Magic numbers/strings — finns hårdkodade värden som borde vara namngivna konstanter?\n"
            "• Funktionslängd — finns funktioner >50 rader som gör för många saker?\n"
            "• Duplicering (DRY) — finns samma logik/block (≥5 rader) på ≥2 ställen?\n"
            "• Död kod — finns utkommenterad kod eller oanvända variabler/importer?\n"
            "• Kommentarer — saknas förklaring för komplex logik, eller finns utdaterade kommentarer?\n"
            "• Konsistens — blandas namngivningsstilar inom samma fil?\n"
            "OBS: Om projektet explicit använder svenska UI-texter är det korrekt — flagga inte svenska strängar."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "security",
        "name": "Säkerheten",
        "emoji": "🔒",
        "phase": "post", "layer": "specialist",
        "modes": [M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är senior applikationssäkerhetsexpert (OWASP Top 10, CWE). Granska koden systematiskt efter verkliga säkerhetsproblem.\n"
            "Kontrollera specifikt:\n"
            "• Injection — SQL/NoSQL/command injection via string-konkatenering?\n"
            "• XSS — okontrollerat HTML-innehåll i DOM (innerHTML, dangerouslySetInnerHTML)?\n"
            "• Auth-kontroll — skyddas alla endpoints/routes som kräver autentisering?\n"
            "• CORS — accepteras origins=* i produktion?\n"
            "• Input-validering — litas okontrollerat på user-supplied data?\n"
            "• Osäker randomness — används Math.random() för säkerhetsändamål?\n"
            "• Path traversal — används user-input i filsökvägskonstruktion?\n"
            "• Sårbara beroenden — används paket med kända CVE:er, eller paketnamn som kan kapas?\n"
            "Rapportera enbart verkliga problem — inte hypotetiska risker utan kodbevis."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "hemlighetsvakten",
        "name": "Hemlighetsvakten",
        "emoji": "🔑",
        "phase": "post", "layer": "specialist",
        "modes": [M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är en dedikerad secret-scanner. Din ENDA uppgift är att hitta hårdkodade hemligheter och credentials i koden.\n"
            "Sök specifikt efter:\n"
            "• API-nycklar — mönster som AKIA…, sk_live_…, sk-…, ghp_…, xox…, AIza…\n"
            "• Lösenord — hårdkodade lösenord i variabler, connection strings eller config?\n"
            "• Tokens — JWT, OAuth-tokens, session-secrets i klartext?\n"
            "• Connection strings — DB-URI:er med inbäddade credentials (postgres://user:pass@…)?\n"
            "• Privata nycklar — -----BEGIN PRIVATE KEY-----, .pem-innehåll?\n"
            "• .env-läckor — committas .env-filer med riktiga värden istället för .env.example?\n"
            "Varje fynd är minst HIGH. Ange exakt var (fil/rad/variabel) och MASKERA värdet i din rapport (visa bara prefix+****).\n"
            "Skriv alla findings och suggestions på svenska.\n"
            "Om inga hemligheter hittas: returnera GODKÄND."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "performance",
        "name": "Prestanda",
        "emoji": "⚡",
        "phase": "post", "layer": "specialist",
        "modes": [M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är prestandaexpert. Identifiera konkreta flaskhalsar i koden.\n"
            "Kontrollera specifikt:\n"
            "• N+1 queries — anropas databas/API i loop istället för batch?\n"
            "• Onödiga re-renders — triggas UI-uppdateringar av orelaterade state-ändringar?\n"
            "• Minneläckor — rensas event listeners, timers, subscriptions vid komponent-unmount?\n"
            "• Tunga synkrona operationer — blockeras UI-tråden av CPU-intensiv kod?\n"
            "• Saknad caching — hämtas samma data upprepade gånger utan cache?\n"
            "• Ineffektiva loopar — O(n²) eller sämre komplexitet där O(n) räcker?\n"
            "• Bundle-storlek — importeras hela bibliotek när enbart en funktion används?\n"
            "• Lazy loading — laddas tunga resurser synkront vid sidstart?\n"
            "Specificera var i koden problemet finns, inte bara att det kan finnas."
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "scalability",
        "name": "Skalbarhet",
        "emoji": "📈",
        "phase": "post", "layer": "specialist",
        "modes": [M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är DevOps/SRE-arkitekt. Granska om systemet kan skalas horisontellt och driftas i produktion.\n"
            "Kontrollera specifikt:\n"
            "• Stateless design — lagras session/state i minnet istället för extern store?\n"
            "• Hårdkodad konfiguration — finns URLs, portar, credentials hårdkodade (borde vara env vars)?\n"
            "• Health endpoints — finns /health eller /healthz för orkestrerare (k8s, ECS)?\n"
            "• Metrics — exponeras nyckeltal (latens, felfrekvens, kö-längd) för övervakning?\n"
            "• Graceful shutdown — hanteras SIGTERM för att avsluta pågående requests rent?\n"
            "• Connection pooling — öppnas ny DB/HTTP-connection per request?\n"
            "• Unbounded queues/lists — kan in-memory köer växa obegränsat under last?\n"
            "• Single point of failure — finns kritiska single points utan fallback?"
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "data_privacy",
        "name": "Dataskydd",
        "emoji": "🛡️",
        "phase": "post", "layer": "specialist",
        "modes": [M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är dataskydds- och GDPR-expert. Granska hur personuppgifter och känslig data hanteras i FÄRDIG KOD.\n"
            "Kontrollera specifikt:\n"
            "• PII i loggar — loggas namn, e-post, IP, ID eller annan PII i klartext?\n"
            "• Okrypterad lagring — lagras lösenord/tokens i plaintext i DB eller fil?\n"
            "• Lösenordshashning — används bcrypt/argon2/scrypt (ALDRIG MD5/SHA1/SHA256 för lösenord)?\n"
            "• Dataminimering — samlas mer data än vad som behövs för ändamålet?\n"
            "• Rätt att radera — finns möjlighet att radera användardata (GDPR Art. 17)?\n"
            "• Tredjepartsdelning — skickas persondata till externa tjänster utan tydlig grund?\n"
            "• Cookie-consent — blockeras icke-nödvändiga cookies tills samtycke ges?\n"
            "• Data-retention — finns strategi för att rensa gammal persondata?"
            + _SEVERITY_GUIDE
        ),
    },
    {
        "id": "testing",
        "name": "Test-agenten",
        "emoji": "🧪",
        "phase": "post", "layer": "specialist",
        "modes": [M_GRANSKA, M_BUGG],
        "model": "google/gemini-2.5-flash",
        "system": (
            "Du är senior QA-ingenjör och testarkitekt. Granska testkvalitet och testbarhet.\n"
            "Kontrollera specifikt:\n"
            "• Täckning — testas happy path, felfall och edge cases?\n"
            "• Inga tester alls — om koden saknar tester helt är det ett HIGH-finding i sig\n"
            "• Input-validering — testas ogiltiga/tomma/extrema inputvärden?\n"
            "• Mock-korrekthet — mockas rätt lager (inte för djupt, inte för ytligt)?\n"
            "• Test-isolation — är varje test oberoende och kan köras i valfri ordning?\n"
            "• Testbarhet — är produktionskoden löst kopplad så den går att testa isolerat?\n"
            "• Testnamn — beskriver testnamnen VAD som testas och under VILKET villkor?\n"
            "• Async-hantering — väntas async-operationer korrekt i tester (await, done-callbacks)?\n"
            "• Flakyness — finns tidsberoende sleep() eller race conditions i testupplägg?"
            + _SEVERITY_GUIDE
        ),
    },
    # ── Buggrapport: rotorsaksanalys (kör i buggläge) ──
    {
        "id": "rotorsak",
        "name": "Rotorsaksanalytikern",
        "emoji": "🔬",
        "phase": "post", "layer": "specialist",
        "modes": [M_BUGG],
        "accepts_images": True,  # uses screenshot when present, runs fine without
        "model": "google/gemini-2.5-flash",
        "max_tokens": 2500,
        "timeout_s": 120,
        "system": (
            "Du är senior felsökare. Du får en buggbeskrivning plus kod och ev. skärmdump/stacktrace. Hitta ROTORSAKEN, inte symptomet.\n"
            "Arbeta så här:\n"
            "• Reproducerbarhet — under vilka exakta villkor uppstår felet? Vad triggar det?\n"
            "• Rotorsak — spåra symptomet bakåt till den faktiska orsaken i koden (inte där felet syns, utan där det orsakas).\n"
            "• Bevis — peka på den specifika koden/raden/skärmdumpsdetaljen som styrker slutsatsen.\n"
            "• Påverkade delar — vilka andra ställen kan ha samma underliggande fel?\n"
            "• Minimal fix-scope — vad är den minsta säkra ändringen som åtgärdar rotorsaken?\n"
            "• 'Anses fixad när' — vilket observerbart villkor bevisar att buggen är borta?\n"
            "findings = rotorsaken + bevis. suggestions = minimal fix-scope + verifieringsvillkor. severity = buggens allvar."
            + _SEVERITY_GUIDE
        ),
    },
]

# Backward-compat views (used by ALL_AGENTS and any legacy mode mapping).
PRE_BUILD_AGENTS = [a for a in SPECIALIST_AGENTS if a.get("phase") == "pre"]
POST_BUILD_AGENTS = [a for a in SPECIALIST_AGENTS if a.get("phase") == "post"]

# Snabbläge — the core seven + visual QA. Fast iteration; djupläge = full team.
_QUICK_AGENT_IDS = {"architecture", "security", "ux", "database", "api",
                    "error_handling", "edge_case", "visual_qa", "rotorsak"}

def agents_for_mode(mode: str, depth: str = "djup") -> list:
    """Return specialist agents for this mode. depth='snabb' → core subset."""
    agents = [a for a in SPECIALIST_AGENTS if mode in a.get("modes", [])]
    if depth == "snabb":
        agents = [a for a in agents if a["id"] in _QUICK_AGENT_IDS]
    return agents

PROMPT_SMITH = {
    "id": "prompt_smith",
    "name": "Promptsmeden",
    "emoji": "✍️",
    "phase": "synth",
    "model": "anthropic/claude-sonnet-4.6",
    "system": (
        "Du är Promptsmeden — en expert på att syntetisera agentfeedback till en komplett, handlingsbar prompt.\n"
        "Du tar emot en idé/kod samt feedback från ett granskningsteam och returnerar ALLTID ett av två JSON-format.\n\n"

        "FORMAT A — när du har TILLRÄCKLIG information för en meningsfull prompt:\n"
        '{"type":"prompt","content":"## CONTEXT\\n[Beskriv projektet, syfte och nuläge]\\n\\n## TASK\\n[Precist vad som ska byggas/fixas]\\n\\n## CONSTRAINTS\\n[Tekniska krav, begränsningar, plattform]\\n\\n## IDENTIFIED ISSUES\\n[Lista de viktigaste fynden från granskningen — HIGH-findings ALLTID med]\\n\\n## ASSUMPTIONS\\n[Antaganden du gjort]\\n\\n## ACCEPTANCE CRITERIA\\n[ ] [Konkret, testbart kriterium]\\n[ ] ..."}'
        "\n\n"

        "FORMAT B — när KRITISK information saknas och du INTE kan skriva en meningsfull prompt:\n"
        '{"type":"questions","intro":"[Kort förklaring varför mer info behövs]","questions":[{"id":"q1","text":"[Fråga]","options":["[Alt 1]","[Alt 2]","Annat / vet ej"]}]}'
        "\n\n"

        "REGLER FÖR IDENTIFIED ISSUES i FORMAT A:\n"
        "• Inkludera ALLA HIGH-severity findings från underkända agenter\n"
        "• Inkludera MEDIUM-findings om de är konkreta och åtgärdbara\n"
        "• Formulera varje finding som en konkret uppgift ('Lägg till try/catch runt fetch-anrop')\n"
        "• Prioritera: säkerhet > korrekthet > prestanda > kodkvalitet\n\n"

        "REGLER FÖR FORMAT B — frågor måste vara kontextspecifika:\n"
        "Generera 1-4 frågor ENBART för luckor som faktiskt blockerar en precis prompt. "
        "Anpassa frågor och alternativ till den specifika kontexten (mobilapp → iOS/Android, CLI → språk/distribution). "
        "ALDRIG generiska webbfrågor om kontexten är uppenbar. "
        "Sista alternativ är alltid 'Annat / vet ej'. Använd svenska om originalidén är på svenska.\n\n"

        "BESLUTSREGEL — välj FORMAT B ENBART om:\n"
        "(1) Systemets syfte är för vagt för att specificera konkret beteende, ELLER\n"
        "(2) Plattform/miljö är oklar och avgör tekniska constraints väsentligt, ELLER\n"
        "(3) Målgruppen är oklar och påverkar arkitektur- eller designbeslut.\n"
        "I alla andra fall: FORMAT A med antaganden under ## ASSUMPTIONS. "
        "En tydlig prompt med antaganden är alltid bättre än fler frågor.\n\n"

        "Returnera ENBART giltig JSON, ingen annan text. "
        "FORMAT A: content på engelska, acceptance criteria på svenska om originalet är på svenska."
    ),
}

KRAV_AGENT = {
    "id": "kravanalytikern",
    "name": "Kravanalytikern",
    "emoji": "📋",
    "phase": "krav",
    "model": "google/gemini-2.5-flash",
    "system": (
        "Du är en senior kravanalytiker. Din uppgift är att omvandla en beställares lösa vision till strukturerade, "
        "tydliga krav som ett IT-team kan arbeta mot.\n\n"
        "Analysera inmatningen och returnera JSON med:\n"
        "• tolkad_ide: en mening som sammanfattar VAD beställaren egentligen vill uppnå\n"
        "• krav: lista med konkreta, numrerade krav i formatet 'K1: [aktiv form] [mätbart mål]'\n"
        "  - Varje krav ska vara implementerbart och testbart\n"
        "  - Max 8 krav — prioritera de viktigaste\n"
        "  - Skriv i samma språk som beställaren\n"
        "• oklarheter: lista med saker som är oklara och behöver klargöras (max 3, lämna tom om allt är tydligt)\n"
        "• utanfor_scope: lista med saker som INTE ska ingå baserat på beskrivningen (max 3)\n\n"
        "Returnera ENBART JSON:\n"
        '{"tolkad_ide":"...","krav":["K1: ...","K2: ..."],"oklarheter":["..."],"utanfor_scope":["..."]}'
    ),
}

COMPLETENESS_AGENT = {
    "id": "kompletthetsgranskaren",
    "name": "Kompletthetsgranskaren",
    "emoji": "✅",
    "phase": "completeness",
    "model": "google/gemini-2.5-flash-lite",
    "system": (
        "Du är en erfaren teknisk specifikationsgranskare. Kontrollera om en given specifikation/prompt "
        "är tillräckligt komplett för att en utvecklare ska kunna implementera den utan att behöva gissa.\n\n"
        "Kontrollera om specen innehåller:\n"
        "• Tydligt syfte och mål\n"
        "• Tekniska krav/begränsningar\n"
        "• Acceptance criteria med RIGOR — happy path, minst ett felfall OCH ett edge case per krav\n"
        "• Spårning — täcker acceptanskriterierna alla identifierade krav (inga föräldralösa krav)?\n"
        "• Hantering av felfall\n"
        "• Integrationer och beroenden\n"
        "• Användarflöden (om relevant)\n\n"
        "Returnera ENBART JSON:\n"
        '{"status":"KOMPLETT"|"OFULLSTÄNDIG","completeness_score":8,'
        '"saknas":["saknad del..."],"styrkor":["styrka..."]}'
        "\ncompleteness_score: heltal 1-10 där 10 = perfekt komplett."
    ),
}

# ── Backloghållaren — loopens ryggrad (granska_kod / buggrapport) ──
BACKLOG_AGENT = {
    "id": "backloghallaren",
    "name": "Backloghållaren",
    "emoji": "🗂️",
    "phase": "synth",
    "model": "google/gemini-2.5-flash",
    "system": (
        "Du är leveransansvarig (product owner). Du får alla fynd från ett granskningsteam och formar dem "
        "till en prioriterad, deduplicerad backlog där varje item kan bli fröet till EN buildbar spec.\n\n"
        "Gör så här:\n"
        "• Deduplicera — slå ihop fynd som flera agenter rapporterat om samma sak till ETT item (lista källagenterna).\n"
        "• Prioritera enligt regel: säkerhet & dataförlust (P0) > korrekthet/buggar (P0/P1) > prestanda (P1) > UX (P1/P2) > kodkvalitet (P2).\n"
        "• Effort — uppskatta S/M/L per item.\n"
        "• Titel — kort, handlingsdriven ('Lägg till rate limiting på /login').\n"
        "• REGRESSION — om prompten listar TIDIGARE ÅTGÄRDADE problem och ett nytt fynd är SAMMA underliggande "
        "problem (även om det formuleras annorlunda): sätt \"regression\": true på det itemet.\n"
        "• DUBBLETT — om prompten listar REDAN ÖPPNA backlog-items och ett fynd är samma underliggande "
        "problem (även omformulerat): utelämna det helt ur ditt svar.\n"
        "• Cappa till de ~10 viktigaste actionable items; nämn i en not om fler rullades till 'senare'.\n\n"
        "Returnera ENBART JSON:\n"
        '{"items":[{"title":"...","priority":"P0"|"P1"|"P2","effort":"S"|"M"|"L",'
        '"finding":"konkret problem","suggestion":"konkret åtgärd","source_agents":["Säkerheten"],"regression":false}],'
        '"note":"ev. kommentar om vad som rullades till senare"}'
    ),
}

# ── Beställarsammanfattaren — klarspråk för icke-kodare (output-lager) ──
BESTALLARE_AGENT = {
    "id": "bestallarsammanfattaren",
    "name": "Beställarsammanfattaren",
    "emoji": "🧑‍💼",
    "phase": "output",
    "model": "google/gemini-2.5-flash",
    "system": (
        "Du översätter en teknisk specifikation och granskningsfynd till klarspråk-svenska som en icke-teknisk "
        "beställare kan läsa, förstå och fatta beslut på. Du får INTE använda kod eller oförklarad jargong.\n\n"
        "Returnera ENBART JSON:\n"
        '{"sammanfattning":"3-5 meningar: vad handlar det om, vad hittades, vad rekommenderas härnäst",'
        '"punkter":[{"vad":"problem/förslag i affärsspråk","varfor":"varför det spelar roll för användare/verksamhet","insats":"liten|mellan|stor"}],'
        '"beslut":["beslut beställaren behöver fatta, om något"]}'
        "\nRegler: expandera akronymer (API, XSS) första gången. Skilj på 'bekräftat problem' och 'rekommendation'. "
        "Översätt teknik till verksamhetsnytta ('kunder kan se andras ordrar', inte 'IDOR i /orders'). "
        "Även 'beslut'-listan ska vara klarspråk — skriv 'attacker via databasen', inte 'SQL-injektion'."
    ),
}

ALL_AGENTS = {a["id"]: a for a in (
    [KRAV_AGENT] + SPECIALIST_AGENTS + [PROMPT_SMITH, BACKLOG_AGENT, COMPLETENESS_AGENT, BESTALLARE_AGENT]
)}


# ──────────────────────────────────────────────
# CORE LOGIC
# ──────────────────────────────────────────────

def _extract_first_json(text: str) -> str | None:
    """Stack-based extraction of first balanced {} object — immune to greedy regex."""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _stringify_finding(x) -> str:
    """Coerce a finding/suggestion item to a readable string.
    Some models return objects like {'issue': '...', 'severity': '...'} instead of plain strings."""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        # Prefer common text keys, else join values
        for k in ("finding", "issue", "problem", "text", "description", "beskrivning", "suggestion", "atgärd", "value"):
            if k in x and isinstance(x[k], str):
                return x[k]
        return " — ".join(str(v) for v in x.values() if v)
    return str(x)


def _parse_agent_json(raw: str) -> dict:
    """Robust JSON parse handling Haiku quirks: markdown blocks, single quotes, extra text."""
    FALLBACK = {"status": "FEL", "findings": ["Ogiltigt agentsvar"], "severity": "HIGH",
                "suggestions": ["Kontrollera agentens output"], "_error": "no_json"}
    if not raw or not raw.strip():
        return FALLBACK
    text = raw.strip()
    # Strip markdown code blocks
    import re as _re
    md = _re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if md:
        text = md.group(1)
    # Try direct parse
    for candidate in [text, _extract_first_json(text)]:
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            # Try ast for single-quote dicts. literal_eval compiles the candidate, so
            # LLM output with invalid escapes (e.g. \` from markdown) emits a SyntaxWarning
            # at <unknown> — harmless here, just silence the noise.
            try:
                import ast as _ast, warnings as _w
                with _w.catch_warnings():
                    _w.simplefilter("ignore", SyntaxWarning)
                    obj = _ast.literal_eval(candidate)
            except Exception:
                continue
        if not isinstance(obj, dict):
            continue
        if obj.get("status") not in ("GODKÄND", "UNDERKÄND"):
            # Salvage a findings-shaped response that just lacks/misspells the status field —
            # infer it rather than throwing the whole agent away as FEL.
            if "findings" in obj or "suggestions" in obj:
                inferred = obj.get("findings") or []
                obj["status"] = "UNDERKÄND" if inferred else "GODKÄND"
            else:
                continue
        obj.setdefault("findings", [])
        obj.setdefault("severity", "MEDIUM")
        obj.setdefault("suggestions", [])
        if not isinstance(obj["findings"], list):
            obj["findings"] = [str(obj["findings"])]
        if not isinstance(obj["suggestions"], list):
            obj["suggestions"] = [str(obj["suggestions"])]
        # Coerce list items to strings — some models return findings as dicts/objects
        obj["findings"] = [_stringify_finding(x) for x in obj["findings"]]
        obj["suggestions"] = [_stringify_finding(x) for x in obj["suggestions"]]
        obj.pop("_error", None)
        return obj
    return FALLBACK


_RETRY_SUFFIX = (
    "\n\nSVARA ENBART med detta JSON-format (inga andra ord):\n"
    '{"status":"GODKÄND"|"UNDERKÄND","findings":["..."],"severity":"LOW"|"MEDIUM"|"HIGH","suggestions":["..."]}'
)

# ──────────────────────────────────────────────
# PROJECT CONTEXT — built dynamically per review
# ──────────────────────────────────────────────

def build_project_context(profile: dict) -> str:
    """
    Turn a project profile dict into a structured context block injected
    into every agent's system prompt.

    Expected profile keys (all optional):
      purpose, stack (list|str), architecture, conventions, constraints, repo, branch
    """
    if not profile:
        return ""
    lines = ["\n\n[PROJEKTKONTEXT]"]
    if profile.get("purpose"):
        lines.append(f"Syfte: {profile['purpose']}")
    stack = profile.get("stack", [])
    if isinstance(stack, list):
        stack = ", ".join(stack)
    if stack:
        lines.append(f"Teknikstack: {stack}")
    if profile.get("architecture"):
        lines.append(f"Arkitektur: {profile['architecture']}")
    if profile.get("conventions"):
        lines.append(f"Kodkonventioner: {profile['conventions']}")
    if profile.get("constraints"):
        lines.append(f"Constraints: {profile['constraints']}")
    if profile.get("repo"):
        branch = profile.get("branch", "main")
        lines.append(f"Repo: {profile['repo']}@{branch}")
    if len(lines) == 1:
        byggsatt = build_byggsatt_block(profile)
        return byggsatt if byggsatt else ""
    lines.append("Beakta dessa constraints i din granskning.")
    return "\n".join(lines) + build_byggsatt_block(profile)


_TEST_LEVEL_TEXT = {
    "inga": "Inga formella testkrav",
    "kritiska": "Tester krävs för kritiska flöden",
    "alltid": "ALLTID tester — varje acceptanskriterium ska ha minst ett testfall",
}
_COMMENT_TEXT = {
    "minimal": "Minimal — kommentera endast VARFÖR, aldrig VAD",
    "standard": "Standard",
    "utforlig": "Utförlig — docstrings på alla publika funktioner",
}

def build_byggsatt_block(profile: dict) -> str:
    """[BYGGSÄTT]-block appended to every specialist's project context.
    The byggsätt governs HOW everything gets built for this project."""
    b = (profile or {}).get("byggsatt") or {}
    lines = []
    lang = b.get("primary_language", "").strip()
    if lang:
        lines.append(f"Primärt språk: {lang} — all exempelkod ska vara {lang}")
    tl = b.get("test_level")
    if tl in _TEST_LEVEL_TEXT:
        fw = b.get("test_framework", "").strip()
        lines.append(f"Testkrav: {_TEST_LEVEL_TEXT[tl]}" + (f" ({fw})" if fw else ""))
    cp = b.get("comment_policy")
    if cp in _COMMENT_TEXT:
        lines.append(f"Kommentarspolicy: {_COMMENT_TEXT[cp]}")
    if not lines:
        return ""
    return ("\n\n[BYGGSÄTT — styrande för detta projekt]\n"
            + "\n".join(lines)
            + "\nFynd och förslag som bryter mot byggsättet är felaktiga.")


_BUILDER_DIRECTIVE = {
    "lovable": "Målbyggare är Lovable: skriv specen som EN sammanhängande prompt utan filsökvägar eller terminalkommandon. Beskriv UI i ord.",
    "cursor": "Målbyggare är Cursor: referera exakta filsökvägar, var diff-orienterad, terminalkommandon tillåtna.",
    "claude_code": "Målbyggare är Claude Code: filsökvägar, stegvis plan och verifieringskommandon ingår.",
    "v0": "Målbyggare är v0: komponentfokuserat, anta React/Tailwind/shadcn-konventioner.",
}
_SPEC_LANG_DIRECTIVE = {
    "sv": "Skriv HELA specen på svenska, inklusive rubriker.",
    "en": "Write the ENTIRE spec in English, including acceptance criteria.",
    "mixed": "Rubriker på engelska, acceptanskriterier på svenska (standard).",
}

def byggsatt_smith_directives(profile: dict) -> str:
    """Absolute spec-writing rules for Promptsmeden (and Kompletthetsgranskaren),
    derived from the project's byggsätt. Empty byggsätt → empty string (today's behavior)."""
    b = (profile or {}).get("byggsatt") or {}
    rules = []
    lang = b.get("primary_language", "").strip()
    if lang:
        rules.append(f"All kod i exempel och kodblock ska vara {lang}.")
    sl = b.get("spec_language")
    if sl in _SPEC_LANG_DIRECTIVE:
        rules.append(_SPEC_LANG_DIRECTIVE[sl])
    tl = b.get("test_level")
    fw = b.get("test_framework", "").strip() or "lämpligt ramverk"
    if tl == "alltid":
        rules.append(f"Varje acceptanskriterium ska ha ett konkret testfall ({fw}). "
                     "Lägg sektionen ## TEST CASES efter acceptance criteria.")
    elif tl == "kritiska":
        rules.append("Inkludera testfall för kritiska flöden under ## TEST CASES.")
    tb = b.get("target_builder")
    if tb in _BUILDER_DIRECTIVE:
        rules.append(_BUILDER_DIRECTIVE[tb])
    conv = (profile or {}).get("conventions", "").strip()
    if conv:
        rules.append(f"Följ kodkonventionerna: {conv}")
    if not rules:
        return ""
    return ("\n\n[BYGGSÄTT — ABSOLUTA REGLER FÖR SPECEN]\n"
            + "\n".join(f"• {r}" for r in rules)
            + "\nEn spec som bryter mot dessa regler är felaktig och måste skrivas om.")


def run_agent(agent: dict, user_input: str, model: str, client,
              project_context: str = "", images: list = None) -> dict:
    """Run a single agent synchronously. Routes to OpenRouter or Anthropic based on model prefix.

    images: optional list of base64 data-URLs (data:image/png;base64,...) for multimodal agents.
    """
    # Feature-gate: a visual agent with no screenshot is a no-op, not a failure.
    if agent.get("needs_visual_input") and not images:
        return {
            "id": agent["id"], "name": agent["name"],
            "emoji": agent["emoji"], "phase": agent.get("phase", "post"),
            "status": "GODKÄND",
            "findings": [],
            "severity": "LOW",
            "suggestions": ["Bifoga en skärmdump för att aktivera visuell granskning."],
            "raw": "", "error": None,
            "skipped": "Ingen skärmdump bifogad — visuell granskning hoppades över.",
        }

    # Resolve model: settings override > agent dict default > global fallback
    agent_model = get_agent_model(agent["id"], agent.get("model", model))
    usage = []  # filled by _or_chat: tokens + cost per call (incl. retries)

    def _call(system_extra="") -> str:
        # 2500 default — Gemini thinking tokens share this budget; too tight truncates the JSON
        max_tok = agent.get("max_tokens", 2500)
        system_text = agent["system"] + project_context + system_extra

        if _is_openrouter_model(agent_model):
            # Build user content — multimodal if images supplied
            if images:
                user_content = [{"type": "text", "text": user_input}]
                for img in images[:6]:  # cap to 6 screenshots per agent
                    user_content.append({"type": "image_url", "image_url": {"url": img}})
            else:
                user_content = user_input
            return _or_chat(
                agent_model,
                [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_content},
                ],
                max_tok,
                usage_out=usage,
            )
        else:
            # Direct Anthropic fallback (bare model name, no provider prefix)
            if images:
                blocks = [{"type": "text", "text": user_input}]
                for img in images[:6]:
                    # data:image/png;base64,XXXX → split media type + data
                    try:
                        header, b64 = img.split(",", 1)
                        media = header.split(":", 1)[1].split(";", 1)[0]
                    except Exception:
                        continue
                    blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": media, "data": b64},
                    })
                msg_content = blocks
            else:
                msg_content = user_input
            resp = client.messages.create(
                model=agent_model,
                max_tokens=max_tok,
                system=system_text,
                messages=[{"role": "user", "content": msg_content}],
            )
            return resp.content[0].text if resp.content else ""

    try:
        raw = _call()
        parsed = _parse_agent_json(raw)

        # If parse failed, retry once with explicit format reminder
        if parsed.get("_error") == "no_json":
            logger.warning("[%s] JSON parse failed, retrying with format hint", agent["id"])
            raw = _call(_RETRY_SUFFIX)
            parsed = _parse_agent_json(raw)

        cost = sum(u["cost_usd"] or 0 for u in usage)
        return {
            "id": agent["id"],
            "name": agent["name"],
            "emoji": agent["emoji"],
            "phase": agent["phase"],
            "status": parsed.get("status", "FEL"),
            "findings": parsed.get("findings", []),
            "severity": parsed.get("severity", "MEDIUM"),
            "suggestions": parsed.get("suggestions", []),
            "raw": raw,
            "error": parsed.get("_error"),
            "model": agent_model,
            "tokens_in": sum(u["tokens_in"] for u in usage),
            "tokens_out": sum(u["tokens_out"] for u in usage),
            "cost_usd": round(cost, 6) if usage else None,
        }
    except Exception as e:
        logger.error("[%s] agent failed: %s", agent["id"], e)
        return {
            "id": agent["id"],
            "name": agent["name"],
            "emoji": agent["emoji"],
            "phase": agent["phase"],
            "status": "FEL",
            "findings": [f"Agent kraschade: {str(e)[:200]}"],
            "severity": "HIGH",
            "suggestions": [],
            "raw": "",
            "error": str(e),
        }


def _call_model(model: str, system: str, user: str, max_tokens: int, client,
                want_json: bool = True, usage_out: list = None) -> str:
    """Unified model call — all provider/model strings go via OpenRouter."""
    if _is_openrouter_model(model):
        return _or_chat(
            model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens,
            want_json=want_json,
            usage_out=usage_out,
        )
    else:
        # Bare model name without provider prefix — direct Anthropic (legacy fallback)
        if not client:
            raise RuntimeError("Varken OpenRouter-nyckel eller Anthropic-nyckel är konfigurerad.")
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text if resp.content else ""


def run_krav_agent(user_input: str, model: str, client, project_context: str = "",
                   usage_out: list = None) -> dict:
    """Run Kravanalytikern. Returns structured requirements dict."""
    FALLBACK = {"tolkad_ide": "", "krav": [], "oklarheter": [], "utanfor_scope": []}
    try:
        krav_model = get_agent_model("kravanalytikern", KRAV_AGENT["model"])
        raw = _call_model(krav_model, KRAV_AGENT["system"] + project_context, user_input, 1000, client,
                          usage_out=usage_out)
        text = raw.strip()
        md = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if md:
            text = md.group(1)
        first = _extract_first_json(text)
        if first:
            try:
                obj = json.loads(first)
                obj.setdefault("tolkad_ide", "")
                obj.setdefault("krav", [])
                obj.setdefault("oklarheter", [])
                obj.setdefault("utanfor_scope", [])
                return obj
            except Exception:
                pass
        return FALLBACK
    except Exception as e:
        logger.error("[kravanalytikern] failed: %s", e)
        return FALLBACK


def run_completeness_agent(spec_content: str, model: str, client, usage_out: list = None,
                           profile: dict = None) -> dict:
    """Run Kompletthetsgranskaren on a generated spec. Returns completeness assessment.
    Gets the same byggsätt directives so it can fail specs that violate them."""
    FALLBACK = {"status": "OKÄND", "completeness_score": 0, "saknas": [], "styrkor": []}
    if not spec_content or not spec_content.strip():
        return FALLBACK
    try:
        comp_model = get_agent_model("completeness", COMPLETENESS_AGENT["model"])
        directives = byggsatt_smith_directives(profile or {})
        comp_system = COMPLETENESS_AGENT["system"]
        if directives:
            comp_system += directives + "\nKontrollera även att specen följer reglerna ovan — bryter den mot dem är den OFULLSTÄNDIG."
        raw = _call_model(
            comp_model, comp_system,
            f"Granska denna specifikation:\n\n{spec_content[:12000]}", 800, client,
            usage_out=usage_out
        )
        text = raw.strip()
        md = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if md:
            text = md.group(1)
        first = _extract_first_json(text)
        if first:
            try:
                obj = json.loads(first)
                obj.setdefault("saknas", [])
                obj.setdefault("styrkor", [])
                return obj
            except Exception:
                pass
        return FALLBACK
    except Exception as e:
        logger.error("[kompletthetsgranskaren] failed: %s", e)
        return FALLBACK


def run_prompt_smith(original_input: str, agent_results: list, model: str, client,
                     usage_out: list = None, profile: dict = None) -> dict:
    """Run Promptsmeden. Returns {type: prompt|questions, ...}.
    profile → byggsätt directives so the spec OBEYS the project's build rules."""
    model = get_agent_model("prompt_smith", PROMPT_SMITH.get("model", "claude-sonnet-4-6"))
    smith_system = PROMPT_SMITH["system"] + byggsatt_smith_directives(profile or {})
    failed = [r for r in agent_results if r.get("status") == "UNDERKÄND"]
    passed = [r for r in agent_results if r.get("status") == "GODKÄND"]
    errors = [r for r in agent_results if r.get("status") == "FEL"]
    passed_names = ", ".join(f"{r['emoji']}{r['name']}" for r in passed) or "Inga"
    summary_parts = [
        f"IDÉ/KOD:\n{original_input[:1500]}",
        f"\nGODKÄND ({len(passed)}): {passed_names}",
        f"\nUNDERKÄND ({len(failed)}) — detaljerad feedback:",
    ]
    for r in failed:
        findings = r.get("findings") or []
        suggestions = r.get("suggestions") or []
        summary_parts.append(
            f"{r['emoji']} {r['name']} [{r.get('severity','?')}]: "
            f"{' | '.join(findings[:3])} → {' | '.join(suggestions[:2])}"
        )
    if errors:
        summary_parts.append(f"\nFEL ({len(errors)}): {', '.join(r['name'] for r in errors)}")
    combined = "\n".join(summary_parts)
    try:
        # 5000 tokens — the ONE user-facing artifact must never truncate mid-spec
        raw = _call_model(model, smith_system, combined, 5000, client, usage_out=usage_out)
        parsed = None
        try:
            parsed = json.loads(raw.strip())
        except json.JSONDecodeError:
            m = re.search(r'\{[\s\S]*\}', raw)
            if m:
                try:
                    parsed = json.loads(m.group())
                except json.JSONDecodeError:
                    pass
        if parsed and parsed.get("type") in ("prompt", "questions"):
            return parsed
        return {"type": "prompt", "content": raw}
    except Exception as e:
        logger.error("[prompt_smith] failed: %s", e)
        # type=error → endpoint skips completeness/bestallare instead of grading garbage
        return {"type": "error", "content": f"Kunde inte generera prompt: {str(e)[:200]}"}


def run_backlog_agent(agent_results: list, model: str, client, project_id: str = "",
                      usage_out: list = None) -> dict:
    """Run Backloghållaren — turns findings into a deduplicated, prioritized backlog.
    Passes previously resolved items so the LLM flags regressions semantically."""
    FALLBACK = {"items": [], "note": ""}
    actionable = [r for r in agent_results if r.get("status") == "UNDERKÄND" and r.get("findings")]
    if not actionable:
        return FALLBACK
    lines = []
    for r in actionable:
        for f in (r.get("findings") or [])[:5]:
            sugg = (r.get("suggestions") or [""])[:1]
            lines.append(f"[{r.get('severity','?')}] ({r['name']}) {f} → {sugg[0] if sugg else ''}")
    combined = "FYND FRÅN GRANSKNINGEN:\n" + "\n".join(lines[:80])
    # Resolved + open items for this project → semantic regression AND duplicate detection
    if project_id:
        with _backlog_lock:
            all_items = _backlog_load()
        proj_items = [i for i in all_items if i.get("project_id") == project_id]
        resolved = [i for i in proj_items if i.get("status") == "åtgärdad"]
        open_items = [i for i in proj_items if i.get("status") in ("öppen", "pågår", "återkommit")]
        if resolved:
            res_lines = "\n".join(f"- {i.get('title','')}: {i.get('finding','')[:150]}" for i in resolved[-20:])
            combined += (
                f"\n\nTIDIGARE ÅTGÄRDADE PROBLEM I DETTA PROJEKT "
                f"(om ett fynd ovan är samma underliggande problem → \"regression\": true):\n{res_lines}"
            )
        if open_items:
            open_lines = "\n".join(f"- {i.get('title','')}: {i.get('finding','')[:150]}" for i in open_items[-30:])
            combined += (
                f"\n\nREDAN ÖPPNA BACKLOG-ITEMS I DETTA PROJEKT "
                f"(om ett fynd ovan är samma underliggande problem → utelämna det helt):\n{open_lines}"
            )
    try:
        bl_model = get_agent_model("backloghallaren", BACKLOG_AGENT["model"])
        raw = _call_model(bl_model, BACKLOG_AGENT["system"], combined, 3000, client, usage_out=usage_out)
        text = raw.strip()
        md = re.search(r'```(?:json)?\s*(\{[\s\S]*\})\s*```', text)
        if md:
            text = md.group(1)
        first = _extract_first_json(text) or text
        if first:
            obj = json.loads(first)
            obj.setdefault("items", [])
            obj.setdefault("note", "")
            return obj
    except Exception as e:
        logger.error("[backloghallaren] failed: %s", e)
    return FALLBACK


def run_bestallare_agent(spec_content: str, agent_results: list, model: str, client,
                         usage_out: list = None) -> dict:
    """Run Beställarsammanfattaren — plain-Swedish business summary for non-coders."""
    FALLBACK = {"sammanfattning": "", "punkter": [], "beslut": []}
    failed = [r for r in agent_results if r.get("status") == "UNDERKÄND"]
    finding_lines = []
    for r in failed:
        for f in (r.get("findings") or [])[:3]:
            finding_lines.append(f"({r['name']}) {f}")
    payload = (
        f"TEKNISK SPECIFIKATION:\n{spec_content[:3000]}\n\n"
        f"VIKTIGA FYND:\n" + "\n".join(finding_lines[:40])
    )
    try:
        b_model = get_agent_model("bestallarsammanfattaren", BESTALLARE_AGENT["model"])
        raw = _call_model(b_model, BESTALLARE_AGENT["system"], payload, 1500, client, usage_out=usage_out)
        first = _extract_first_json(raw.strip())
        if first:
            obj = json.loads(first)
            obj.setdefault("sammanfattning", "")
            obj.setdefault("punkter", [])
            obj.setdefault("beslut", [])
            return obj
    except Exception as e:
        logger.error("[bestallarsammanfattaren] failed: %s", e)
    return FALLBACK


# ──────────────────────────────────────────────
# ENDPOINTS
# ──────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/settings")
async def get_settings():
    s = load_settings()
    # Mask ALL credentials — never return raw keys to the browser
    key = s.get("api_key", "")
    if key:
        s["api_key"] = "sk-***" + key[-4:]
    or_key = s.get("openrouter_key", "")
    if or_key:
        s["openrouter_key"] = "sk-or-***" + or_key[-4:]
    sb_key = s.get("supabase_key", "")
    if sb_key:
        s["supabase_key"] = "***" + sb_key[-4:]
    gh = s.get("github_token", "")
    if gh:
        s["github_token"] = "***" + gh[-4:]
    s.setdefault("agent_models", {})
    return s


@app.post("/api/settings")
async def post_settings(payload: dict):
    s = load_settings()
    if "api_key" in payload and payload["api_key"] and not payload["api_key"].startswith("sk-***"):
        s["api_key"] = payload["api_key"]
    if "openrouter_key" in payload and payload["openrouter_key"] and not payload["openrouter_key"].startswith("sk-or-***"):
        s["openrouter_key"] = payload["openrouter_key"]
    if "agent_models" in payload and isinstance(payload["agent_models"], dict):
        s["agent_models"] = payload["agent_models"]
    if "model" in payload:
        s["model"] = payload["model"]
    if "supabase_url" in payload:
        s["supabase_url"] = payload["supabase_url"]
    if "supabase_key" in payload and payload["supabase_key"] and not payload["supabase_key"].startswith("***"):
        s["supabase_key"] = payload["supabase_key"]
    if "github_token" in payload and payload["github_token"] and not payload["github_token"].startswith("***"):
        s["github_token"] = payload["github_token"]
    if "self_repo" in payload:
        s["self_repo"] = payload["self_repo"]
    if "self_branch" in payload:
        s["self_branch"] = payload["self_branch"]
    save_settings(s)
    key = s.get("api_key", "")
    if key:
        s["api_key"] = "sk-***" + key[-4:]
    sb_key = s.get("supabase_key", "")
    if sb_key:
        s["supabase_key"] = "***" + sb_key[-4:]
    gh = s.get("github_token", "")
    if gh:
        s["github_token"] = "***" + gh[-4:]
    return s


# ──────────────────────────────────────────────
# LIVE PROGRESS — real agent status during a run (polled by the UI)
# ──────────────────────────────────────────────
_progress: dict = {}
_progress_lock = threading.Lock()

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
        # GC entries older than 15 min
        cutoff = entry["updated"] - 900
        for k in [k for k, v in _progress.items() if v.get("updated", 0) < cutoff]:
            _progress.pop(k, None)


@app.get("/api/progress/{run_id}")
async def get_progress(run_id: str):
    with _progress_lock:
        return _progress.get(run_id, {"phase": "okänd", "agents": {}})


# Legacy mode names → new mode names (backward compat with older frontend payloads)
_MODE_ALIASES = {"pre": "ny_funktion", "post": "granska_kod", "both": "granska_kod"}
_VALID_MODES = ("ny_funktion", "granska_kod", "buggrapport")

@app.post("/api/review")
async def review(payload: dict):
    """
    payload: {
        mode: "ny_funktion" | "granska_kod" | "buggrapport",
        input_text: str,       # idea, code, or bug description
        context: str,          # optional extra context
        images: [dataURL],     # optional screenshots (granska_kod / buggrapport)
        project_id: str
    }
    """
    mode = payload.get("mode", "ny_funktion")
    mode = _MODE_ALIASES.get(mode, mode)
    if mode not in _VALID_MODES:
        mode = "ny_funktion"
    run_id = str(payload.get("run_id", ""))[:64]
    input_text = payload.get("input_text", "").strip()
    context = payload.get("context", "").strip()
    project_id = payload.get("project_id", "")
    images = payload.get("images", []) or []
    if not isinstance(images, list):
        images = []
    images = [i for i in images if isinstance(i, str) and i.startswith("data:image")][:6]

    if not input_text:
        return JSONResponse({"error": "Ingen text angiven."}, status_code=400)

    MAX_INPUT = 80_000
    if len(input_text) > MAX_INPUT:
        return JSONResponse(
            {"error": f"Texten är för lång ({len(input_text):,} tecken). Max {MAX_INPUT:,} tecken. "
                      "Välj en specifik mapp i mappväljaren för att minska mängden kod."},
            status_code=400
        )

    s = load_settings()
    client = get_client()  # Anthropic fallback (may be None — OpenRouter is primary)
    if not s.get("openrouter_key", "").strip() and not client:
        return JSONResponse(
            {"error": "Ingen API-nyckel konfigurerad. Gå till Inställningar och lägg till din OpenRouter-nyckel."},
            status_code=400,
        )

    model = s.get("model", "google/gemini-2.5-flash")

    # Select specialist agents that declare this mode (depth: snabb=core 7, djup=full team)
    depth = payload.get("depth", "djup")
    if depth not in ("snabb", "djup"):
        depth = "djup"
    agents = agents_for_mode(mode, depth)
    is_review_mode = mode in ("granska_kod", "buggrapport")

    # Build full input for agents
    file_manifest = payload.get("file_manifest", "")
    profile = payload.get("profile", {}) or {}
    project_context = build_project_context(profile)

    input_label = {
        "ny_funktion": "IDÉ ATT GRANSKA",
        "granska_kod": "KOD ATT GRANSKA",
        "buggrapport": "BUGGRAPPORT + KOD",
    }[mode]

    full_input = input_text
    if context or file_manifest:
        parts = []
        if file_manifest:
            parts.append(file_manifest)
        if context:
            parts.append(f"KONTEXT:\n{context}")
        parts.append(f"{input_label}:\n{input_text}")
        full_input = "\n\n".join(parts)

    loop = asyncio.get_running_loop()

    synth_usage = []  # tokens/cost from krav + synthesis agents (specialists report their own)
    _progress_set(run_id, phase="krav", total=len(agents))

    # ── Step 1: Kravanalytikern ──
    # ny_funktion: GATE — specialists need krav context to review a vague idea.
    # granska_kod/buggrapport: input is already concrete code → krav runs CONCURRENTLY
    # with the specialists (saves 4-8s of critical path; krav_result still shown in UI).
    async def _run_krav():
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(executor, run_krav_agent, full_input, model, client,
                                     project_context, synth_usage),
                timeout=90.0
            )
        except asyncio.TimeoutError:
            logger.warning("[kravanalytikern] timeout")
            return {"tolkad_ide": "", "krav": [], "oklarheter": [], "utanfor_scope": []}

    krav_result = {}
    krav_system_context = ""
    krav_task = None
    if is_review_mode:
        krav_task = asyncio.ensure_future(_run_krav())
    else:
        krav_result = await _run_krav()
        if krav_result.get("tolkad_ide") or krav_result.get("krav"):
            krav_lines = "\n".join(f"- {k}" for k in krav_result.get("krav", []))
            krav_system_context = (
                f"\n\n[IDENTIFIERADE KRAV]\n"
                f"Beställarens idé: {krav_result.get('tolkad_ide','')}\n"
                f"Krav:\n{krav_lines}"
            )

    # ── Step 2: Run specialist agents in parallel ──
    # krav injected via system context, user input stays clean.
    # Screenshots passed only to agents that declare needs_visual_input.
    enriched_input = full_input
    combined_context = project_context + krav_system_context

    _progress_set(run_id, phase="specialister")

    async def run_with_timeout(agent):
        wants_img = agent.get("needs_visual_input") or agent.get("accepts_images")
        agent_images = images if wants_img else None
        agent_timeout = float(agent.get("timeout_s", 95))
        _progress_set(run_id, agent=(agent["id"], "kör"))
        try:
            r = await asyncio.wait_for(
                loop.run_in_executor(executor, run_agent, agent, enriched_input,
                                     model, client, combined_context, agent_images),
                timeout=agent_timeout
            )
        except asyncio.TimeoutError:
            r = {
                "id": agent["id"], "name": agent["name"],
                "emoji": agent["emoji"], "phase": agent.get("phase", "post"),
                "status": "FEL", "findings": [f"Timeout — agenten svarade inte inom {agent_timeout:.0f}s"],
                "severity": "HIGH", "suggestions": [], "raw": "", "error": "timeout"
            }
        _progress_set(run_id, agent=(agent["id"], r.get("status", "FEL")))
        return r

    try:
        results = list(await asyncio.wait_for(
            asyncio.gather(*[run_with_timeout(a) for a in agents]),
            timeout=200.0
        ))
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Granskningen tog för lång tid (>200s). Försök med mindre kod eller färre agenter."}, status_code=504)

    # Collect krav result if it ran concurrently (review modes)
    if krav_task is not None:
        krav_result = await krav_task

    _progress_set(run_id, phase="syntes")

    # ── Step 3+4: Backloghållaren + Promptsmeden in PARALLEL (independent of each other) ──
    backlog_result = {"items": [], "note": ""}
    backlog_items = []

    async def _run_backlog():
        if not is_review_mode:
            return {"items": [], "note": ""}
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(executor, run_backlog_agent, results, model, client,
                                     project_id, synth_usage),
                timeout=75.0
            )
        except asyncio.TimeoutError:
            logger.warning("[backloghallaren] timeout")
            return {"items": [], "note": ""}

    async def _run_smith():
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(executor, run_prompt_smith, input_text, results,
                                     model, client, synth_usage, profile),
                timeout=120.0
            )
        except asyncio.TimeoutError:
            logger.warning("[prompt_smith] timeout")
            return {"type": "error", "content": "Promptsmeden svarade inte i tid — försök igen."}

    backlog_result, smith_result = await asyncio.gather(_run_backlog(), _run_smith())

    # ── Step 5+6: Kompletthet + Beställarsammanfattning in PARALLEL (both consume the spec) ──
    spec_content = smith_result.get("content", "") if smith_result.get("type") == "prompt" else ""
    completeness_result = {}
    bestallare_result = {}
    if spec_content:
        async def _run_completeness():
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(executor, run_completeness_agent, spec_content,
                                         model, client, synth_usage, profile),
                    timeout=90.0
                )
            except asyncio.TimeoutError:
                logger.warning("[kompletthetsgranskaren] timeout")
                return {}

        async def _run_bestallare():
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(executor, run_bestallare_agent, spec_content, results,
                                         model, client, synth_usage),
                    timeout=90.0
                )
            except asyncio.TimeoutError:
                logger.warning("[bestallarsammanfattaren] timeout")
                return {}

        completeness_result, bestallare_result = await asyncio.gather(_run_completeness(), _run_bestallare())

    # Summary stats
    approved = sum(1 for r in results if r["status"] == "GODKÄND")
    rejected = sum(1 for r in results if r["status"] == "UNDERKÄND")
    errors = sum(1 for r in results if r["status"] == "FEL")

    # Cost summary — specialists carry their own usage; synthesis collected in synth_usage
    tok_in = sum(r.get("tokens_in") or 0 for r in results) + sum(u["tokens_in"] for u in synth_usage)
    tok_out = sum(r.get("tokens_out") or 0 for r in results) + sum(u["tokens_out"] for u in synth_usage)
    cost_total = (sum(r.get("cost_usd") or 0 for r in results)
                  + sum(u["cost_usd"] or 0 for u in synth_usage))
    cost_summary = {
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "total_usd": round(cost_total, 4),
        "by_agent": sorted(
            [{"name": r["name"], "cost_usd": round(r.get("cost_usd") or 0, 5)} for r in results],
            key=lambda x: -x["cost_usd"])[:5],
    }

    session_id = str(uuid.uuid4())
    session_name = auto_name(input_text)
    stats_dict = {"total": len(results), "approved": approved, "rejected": rejected, "errors": errors}

    # Persist backlog (review modes) — groomed items become the loop's work plan
    if is_review_mode and backlog_result.get("items"):
        try:
            backlog_items = await loop.run_in_executor(
                executor, backlog_add_items, backlog_result["items"], project_id, session_id
            )
        except Exception as e:
            logger.error("backlog persist failed: %s", e)

    save_result = await loop.run_in_executor(executor, save_session,
        session_id, session_name, mode, input_text, context,
        results, smith_result, stats_dict, project_id
    )

    _progress_set(run_id, phase="klar")

    return {
        "session_id": session_id,
        "session_name": session_name,
        "mode": mode,
        "results": results,
        "smith": smith_result,
        "krav_result": krav_result,
        "completeness_result": completeness_result,
        "bestallare_result": bestallare_result,
        "backlog_result": backlog_result,
        "backlog_items": backlog_items,
        "final_prompt": smith_result.get("content", "") if smith_result.get("type") == "prompt" else "",
        "stats": stats_dict,
        "cost_summary": cost_summary,
        "saved": save_result,
    }


# ──────────────────────────────────────────────
# BACKLOG ENDPOINTS — the loop's work plan
# ──────────────────────────────────────────────

@app.get("/api/backlog")
async def get_backlog(project_id: str = ""):
    """List backlog items, newest first. Optionally filtered by project."""
    items = _backlog_load()
    if project_id:
        items = [i for i in items if i.get("project_id") == project_id]
    # Sort: open/regressed first, then by priority, then newest
    prio_rank = {"P0": 0, "P1": 1, "P2": 2}
    status_rank = {"återkommit": 0, "öppen": 1, "pågår": 2, "åtgärdad": 3}
    items.sort(key=lambda i: (
        status_rank.get(i.get("status"), 9),
        prio_rank.get(i.get("priority"), 9),
        i.get("created_at", ""),
    ))
    return {"items": items}


@app.patch("/api/backlog/{item_id}")
async def update_backlog_item(item_id: str, payload: dict):
    """Update a backlog item's status (öppen|pågår|åtgärdad|återkommit)."""
    new_status = payload.get("status")
    if new_status not in VALID_STATUSES:
        return JSONResponse({"error": f"Ogiltig status. Tillåtna: {', '.join(VALID_STATUSES)}"}, status_code=400)
    with _backlog_lock:
        items = _backlog_load()
        found = False
        for it in items:
            if it.get("id") == item_id:
                it["status"] = new_status
                it["updated_at"] = datetime.now().isoformat(timespec="seconds")
                found = True
                break
        if found:
            tmp = BACKLOG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(BACKLOG_FILE)
    if not found:
        return JSONResponse({"error": "Item hittades inte."}, status_code=404)
    return {"ok": True, "id": item_id, "status": new_status}


@app.post("/api/backlog/{item_id}/to-spec")
async def backlog_to_spec(item_id: str, payload: dict):
    """Turn a single backlog item into a complete spec via Promptsmeden — closes the loop."""
    items = _backlog_load()
    item = next((i for i in items if i.get("id") == item_id), None)
    if not item:
        return JSONResponse({"error": "Item hittades inte."}, status_code=404)

    s = load_settings()
    client = get_client()
    if not s.get("openrouter_key", "").strip() and not client:
        return JSONResponse({"error": "Ingen API-nyckel konfigurerad."}, status_code=400)
    model = s.get("model", "google/gemini-2.5-flash")

    # Seed Promptsmeden with the item as a single high-priority finding
    seed_results = [{
        "id": "backlog_seed",
        "name": " · ".join(item.get("source_agents", [])) or "Backlog",
        "emoji": "🗂️",
        "status": "UNDERKÄND",
        "findings": [item.get("finding", item.get("title", ""))],
        "severity": {"P0": "HIGH", "P1": "MEDIUM", "P2": "LOW"}.get(item.get("priority"), "MEDIUM"),
        "suggestions": [item.get("suggestion", "")] if item.get("suggestion") else [],
    }]
    seed_input = item.get("title", "")

    loop = asyncio.get_running_loop()
    usage = []
    profile = payload.get("profile", {}) or {}  # byggsätt governs spec writing
    try:
        smith_result = await asyncio.wait_for(
            loop.run_in_executor(executor, run_prompt_smith, seed_input, seed_results,
                                 model, client, usage, profile),
            timeout=120.0)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Promptsmeden svarade inte i tid — försök igen."}, status_code=504)
    spec_content = smith_result.get("content", "") if smith_result.get("type") == "prompt" else ""

    completeness_result = {}
    bestallare_result = {}
    if spec_content:
        # Both consume the spec — run in parallel with timeouts
        async def _comp():
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(executor, run_completeness_agent, spec_content,
                                         model, client, usage, profile), timeout=90.0)
            except asyncio.TimeoutError:
                return {}
        async def _best():
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(executor, run_bestallare_agent, spec_content,
                                         seed_results, model, client, usage), timeout=90.0)
            except asyncio.TimeoutError:
                return {}
        completeness_result, bestallare_result = await asyncio.gather(_comp(), _best())

    # Persist the spec as a session — specs from the loop must survive a page close
    session_id = str(uuid.uuid4())
    if spec_content:
        await loop.run_in_executor(executor, save_session,
            session_id, f"📋 Spec: {item.get('title','')[:60]}", "backlog_spec",
            item.get("finding", ""), item.get("suggestion", ""),
            [], smith_result,
            {"total": 0, "approved": 0, "rejected": 0, "errors": 0},
            item.get("project_id", ""),
        )

    # enqueue:true — fynd → spec → byggkö in one click; backlog item moves to pågår
    queue_item = None
    if spec_content and payload.get("enqueue"):
        queue_item = queue_create_item(
            item.get("project_id", ""),
            item.get("title", ""),
            spec_content,
            (bestallare_result or {}).get("sammanfattning", ""),
            {"type": "backlog", "backlog_item_id": item_id, "session_id": session_id},
        )
        with _backlog_lock:
            bitems = _backlog_load()
            for b in bitems:
                if b.get("id") == item_id:
                    b["status"] = "pågår"
                    b["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    break
            tmp = BACKLOG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(bitems, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(BACKLOG_FILE)

    cost = sum(u["cost_usd"] or 0 for u in usage)
    return {
        "item": item,
        "smith": smith_result,
        "final_prompt": spec_content,
        "completeness_result": completeness_result,
        "bestallare_result": bestallare_result,
        "session_id": session_id if spec_content else None,
        "queue_item": queue_item,
        "cost_summary": {"total_usd": round(cost, 4),
                         "tokens_in": sum(u["tokens_in"] for u in usage),
                         "tokens_out": sum(u["tokens_out"] for u in usage)},
    }


_VERIFY_SYSTEM = (
    "Du är en noggrann fixverifierare. Du får ETT specifikt problem som tidigare hittats, "
    "åtgärdsförslaget, och den NYA koden (ev. + skärmdump). Din enda uppgift: avgör om DETTA problem är åtgärdat.\n"
    "• Verifiera mot koden — inte mot löften eller kommentarer.\n"
    "• Om problemet är delvis åtgärdat: fixad=false och lista exakt vad som kvarstår.\n"
    "• Bedöm ENBART det angivna problemet — rapportera inte nya/andra fynd.\n"
    "Returnera ENBART JSON:\n"
    '{"fixad":true|false,"motivering":"konkret bevis från koden","kvarstaende":["det som saknas..."]}'
)

@app.post("/api/backlog/{item_id}/verify")
async def backlog_verify_fix(item_id: str, payload: dict):
    """Verify a fix against the item's ORIGINAL finding. fixad → åtgärdad, else stays open.
    payload: { code: str, images: [dataURL] (optional) }"""
    items = _backlog_load()
    item = next((i for i in items if i.get("id") == item_id), None)
    if not item:
        return JSONResponse({"error": "Item hittades inte."}, status_code=404)
    code = (payload.get("code") or "").strip()
    if not code:
        return JSONResponse({"error": "Klistra in den uppdaterade koden att verifiera mot."}, status_code=400)
    images = [i for i in (payload.get("images") or [])
              if isinstance(i, str) and i.startswith("data:image")][:3]

    s = load_settings()
    client = get_client()
    if not s.get("openrouter_key", "").strip() and not client:
        return JSONResponse({"error": "Ingen API-nyckel konfigurerad."}, status_code=400)

    user_text = (
        f"URSPRUNGLIGT PROBLEM:\n{item.get('finding','')}\n\n"
        f"FÖRESLAGEN ÅTGÄRD:\n{item.get('suggestion','') or '(ingen specifik)'}\n\n"
        f"NY KOD ATT VERIFIERA:\n{code[:40_000]}"
    )
    verify_agent = {
        "id": "fixverifieraren", "name": "Fixverifieraren", "emoji": "🔍",
        "phase": "verify", "system": _VERIFY_SYSTEM,
        "model": "google/gemini-2.5-flash", "max_tokens": 1200,
    }
    loop = asyncio.get_running_loop()
    usage = []
    try:
        raw = await asyncio.wait_for(
            loop.run_in_executor(executor, lambda: _or_chat(
                get_agent_model("fixverifieraren", verify_agent["model"]),
                [{"role": "system", "content": _VERIFY_SYSTEM},
                 {"role": "user", "content": (
                     [{"type": "text", "text": user_text}] +
                     [{"type": "image_url", "image_url": {"url": img}} for img in images]
                 ) if images else user_text}],
                1200, usage_out=usage)),
            timeout=90.0)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Verifieringen tog för lång tid."}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": f"Verifiering misslyckades: {str(e)[:150]}"}, status_code=502)

    verdict = {"fixad": False, "motivering": "Kunde inte tolka verifierarens svar.", "kvarstaende": []}
    first = _extract_first_json(raw.strip())
    if first:
        try:
            obj = json.loads(first)
            verdict = {
                "fixad": bool(obj.get("fixad")),
                "motivering": _stringify_finding(obj.get("motivering", "")),
                "kvarstaende": [_stringify_finding(x) for x in (obj.get("kvarstaende") or [])],
            }
        except Exception:
            pass

    # fixad → åtgärdad (so the regression detector can watch it); else stays as-is
    if verdict["fixad"]:
        with _backlog_lock:
            items = _backlog_load()
            for it in items:
                if it.get("id") == item_id:
                    it["status"] = "åtgärdad"
                    it["updated_at"] = datetime.now().isoformat(timespec="seconds")
                    break
            tmp = BACKLOG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(BACKLOG_FILE)

    cost = sum(u["cost_usd"] or 0 for u in usage)
    return {"item_id": item_id, "verdict": verdict,
            "new_status": "åtgärdad" if verdict["fixad"] else item.get("status"),
            "cost_usd": round(cost, 5)}


@app.post("/api/build-queue/{item_id}/review")
async def build_queue_review(item_id: str, payload: dict):
    """The closing loop: built code → full granska_kod review + verify against source finding
    → verdict klar | behover_dig. Today a button; tomorrow the builder calls this itself.
    payload: { code?: str, images?: [dataURL], profile?: {} } — code in body is saved as
    the result first, so the manual 'Klar? Klistra in resultatet' flow is ONE call."""
    items = _queue_load()
    item = next((i for i in items if i.get("id") == item_id and not i.get("deleted_at")), None)
    if not item:
        return JSONResponse({"error": "Item hittades inte."}, status_code=404)

    # Inline result (manual flow): save it via the same idempotent path
    code = (payload.get("code") or "").strip()
    if code:
        r = await build_queue_result(item_id, {"attempt_nr": item.get("attempt_nr"), "code": code,
                                               "status": "byggd"})
        if isinstance(r, JSONResponse):
            return r
        items = _queue_load()
        item = next((i for i in items if i.get("id") == item_id), None)

    if not item.get("result_ref"):
        return JSONResponse({"error": "Inget byggresultat att granska — klistra in koden eller skicka /result först."}, status_code=409)

    # Load the built code from the side file
    try:
        result_data = json.loads((BUILD_RESULTS_DIR / item["result_ref"]).read_text(encoding="utf-8"))
    except Exception:
        return JSONResponse({"error": "Kunde inte läsa byggresultatet."}, status_code=500)
    built_code = result_data.get("code") or result_data.get("diff") or ""
    if not built_code.strip():
        return JSONResponse({"error": "Byggresultatet är tomt."}, status_code=409)

    with _queue_lock:
        items = _queue_load()
        item = next((i for i in items if i.get("id") == item_id), None)
        item["review_started_at"] = datetime.now().isoformat(timespec="seconds")
        _queue_write(items)

    profile = payload.get("profile") or {}
    # Full team review of the built code — reuses the entire pipeline in-process.
    review_payload = {
        "mode": "granska_kod",
        "input_text": built_code[:78_000],
        "context": f"Detta är ett bygge av specen: {item['title']}\n\nSPEC (utdrag):\n{item['spec_markdown'][:4000]}",
        "images": payload.get("images") or [],
        "project_id": item.get("project_id", ""),
        "profile": profile,
        "depth": payload.get("depth", "djup"),
    }
    review_res = await review(review_payload)
    if isinstance(review_res, JSONResponse):
        with _queue_lock:
            items = _queue_load()
            item = next((i for i in items if i.get("id") == item_id), None)
            item["review_started_at"] = None
            _queue_write(items)
        return review_res

    # New P0s counted on the RAW groomed items (pre-dedup) — dedup would mask persisting P0s
    raw_items = (review_res.get("backlog_result") or {}).get("items", [])
    new_p0 = [i for i in raw_items if i.get("priority") == "P0"]

    # Verify against the ORIGINAL backlog finding if this spec came from one
    fixad = None
    verify_verdict = {}
    src = item.get("source") or {}
    if src.get("backlog_item_id"):
        v = await backlog_verify_fix(src["backlog_item_id"], {"code": built_code[:40_000],
                                                              "images": payload.get("images") or []})
        if not isinstance(v, JSONResponse):
            verify_verdict = v.get("verdict", {})
            fixad = bool(verify_verdict.get("fixad"))

    # The verdict rule: klar = no new P0 AND (no source finding OR source finding fixed)
    is_klar = (len(new_p0) == 0) and (fixad is None or fixad)
    verdict = {
        "fixad": fixad,
        "motivering": verify_verdict.get("motivering", ""),
        "kvarstaende": (verify_verdict.get("kvarstaende") or []) + [i.get("title", "") for i in new_p0],
        "new_p0": len(new_p0),
        "review_session_id": review_res.get("session_id"),
    }

    with _queue_lock:
        items = _queue_load()
        item = next((i for i in items if i.get("id") == item_id), None)
        item["status"] = "klar" if is_klar else "behover_dig"
        item["last_verdict"] = verdict
        item["review_started_at"] = None
        _queue_log(item, "granskad", f"{'klar' if is_klar else 'behover_dig'} · {len(new_p0)} nya P0")
        _queue_write(items)

    return {
        "item": item,
        "verdict": verdict,
        "new_status": item["status"],
        "review_session_id": review_res.get("session_id"),
        "review_stats": review_res.get("stats"),
        "cost_summary": review_res.get("cost_summary"),
    }


# Filetypes to include in code review
INCLUDE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".env.example", ".md",
    ".sql", ".sh", ".bat", ".txt"
}
EXCLUDE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    "venv", ".venv", "coverage", ".cache", "vendor"
}
MAX_FILES = 60
MAX_TOTAL_CHARS = 60_000
MAX_FILE_CHARS = 8_000



@app.get("/api/github/repos")
async def github_list_repos():
    """List all repos for the authenticated GitHub user."""
    s = load_settings()
    token = s.get("github_token", "").strip()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        loop = asyncio.get_running_loop()
        resp = await asyncio.wait_for(
            loop.run_in_executor(executor, lambda: httpx.get(
                "https://api.github.com/user/repos?per_page=100&sort=updated&affiliation=owner",
                headers=headers, timeout=10.0
            )),
            timeout=15.0
        )
        if resp.status_code == 200:
            repos = [
                {"full_name": r["full_name"], "name": r["name"],
                 "private": r["private"], "default_branch": r.get("default_branch", "main")}
                for r in resp.json()
            ]
            return {"repos": repos}
        return {"repos": [], "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"repos": [], "error": str(e)[:100]}


@app.get("/api/github/branches")
async def github_list_branches(repo: str):
    """List branches for a given repo."""
    s = load_settings()
    token = s.get("github_token", "").strip()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        loop = asyncio.get_running_loop()
        resp = await asyncio.wait_for(
            loop.run_in_executor(executor, lambda: httpx.get(
                f"https://api.github.com/repos/{repo}/branches?per_page=50",
                headers=headers, timeout=10.0
            )),
            timeout=15.0
        )
        if resp.status_code == 200:
            branches = [b["name"] for b in resp.json()]
            return {"branches": branches}
        return {"branches": [], "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"branches": [], "error": str(e)[:100]}

@app.get("/api/github/tree")
async def github_tree(repo: str, branch: str = "main"):
    """Return top-level directories for folder picker."""
    s = load_settings()
    token = s.get("github_token", "").strip()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        loop = asyncio.get_running_loop()
        r = await asyncio.wait_for(
            loop.run_in_executor(executor, lambda: httpx.get(
                f"https://api.github.com/repos/{repo}/git/trees/{branch}",
                headers=headers, timeout=10.0
            )),
            timeout=15.0
        )
        if r.status_code != 200:
            return {"dirs": [], "error": f"HTTP {r.status_code}"}
        tree = r.json().get("tree", [])
        dirs = sorted([
            item["path"] for item in tree
            if item["type"] == "tree"
            and not item["path"].startswith(".")
            and item["path"] not in ("node_modules", "__pycache__", "dist", "build", "venv", ".git")
        ])
        files = sorted([
            item["path"] for item in tree
            if item["type"] == "blob"
        ])
        return {"dirs": dirs, "files": files}
    except Exception as e:
        return {"dirs": [], "error": str(e)[:80]}

@app.post("/api/github/fetch")
async def github_fetch(payload: dict):
    """
    payload: { repo: "owner/repo", branch: "main", paths: [] | path: "" }
    Returns: { files: [{path, content, size}], total_chars, truncated,
               file_manifest: str, skipped_files: [str] }

    `paths` (list) filters to any file whose path starts with one of the given prefixes.
    `path` (str) is the legacy single-folder form — still supported.
    """
    repo = payload.get("repo", "").strip().removeprefix("https://github.com/").lstrip("/")
    branch = payload.get("branch", "main").strip() or "main"

    # Normalise path filter — accept both `paths: [...]` and legacy `path: "..."`
    raw_paths = payload.get("paths") or []
    if not raw_paths and payload.get("path"):
        raw_paths = [payload["path"]]
    path_filters = [p.strip().lstrip("/") for p in raw_paths if p and p.strip()]

    if not repo or "/" not in repo:
        return JSONResponse({"error": "Ogiltigt repo-format. Använd: owner/repo"}, status_code=400)

    s = load_settings()
    token = s.get("github_token", "")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # 1. Get file tree
    tree_url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    try:
        tree_resp = await asyncio.get_running_loop().run_in_executor(
            executor,
            lambda: __import__("httpx").get(tree_url, headers=headers, timeout=15.0)
        )
    except Exception as e:
        return JSONResponse({"error": f"Kunde inte nå GitHub: {e}"}, status_code=502)

    if tree_resp.status_code == 404:
        return JSONResponse({"error": "Repo eller branch hittades inte. Kontrollera att repot är publikt eller att din GitHub-token har åtkomst."}, status_code=404)
    if tree_resp.status_code == 401:
        return JSONResponse({"error": "GitHub-token saknas eller är ogiltig."}, status_code=401)
    if tree_resp.status_code != 200:
        return JSONResponse({"error": f"GitHub API fel: {tree_resp.status_code}"}, status_code=502)

    tree_data = tree_resp.json()

    def _path_matches(path: str) -> bool:
        if not path_filters:
            return True
        return any(path.startswith(pf) for pf in path_filters)

    all_files = [
        item for item in tree_data.get("tree", [])
        if item["type"] == "blob"
        and any(item["path"].endswith(ext) for ext in INCLUDE_EXTENSIONS)
        and not any(excl in item["path"].split("/") for excl in EXCLUDE_DIRS)
        and _path_matches(item["path"])
        and item.get("size", 0) < 100_000
    ]

    # Sort: src/ first, then by size ascending
    all_files.sort(key=lambda f: (0 if f["path"].startswith("src/") else 1, f.get("size", 0)))
    selected = all_files[:MAX_FILES]

    # 2. Fetch file contents in parallel
    async def fetch_file(item):
        url = f"https://api.github.com/repos/{repo}/contents/{item['path']}?ref={branch}"
        try:
            resp = await asyncio.get_running_loop().run_in_executor(
                executor,
                lambda: __import__("httpx").get(url, headers=headers, timeout=10.0)
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            import base64
            content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            truncated_content = content[:MAX_FILE_CHARS]
            return {
                "path": item["path"],
                "content": truncated_content,
                "size": len(content),
                "truncated": len(content) > MAX_FILE_CHARS,
            }
        except Exception:
            return None

    file_results = await asyncio.gather(*[fetch_file(f) for f in selected])
    files = [f for f in file_results if f]

    # 3. Apply total char budget
    total_chars = 0
    output_files = []
    skipped_files = []
    for f in files:
        if total_chars + len(f["content"]) > MAX_TOTAL_CHARS:
            skipped_files.append(f["path"])
        else:
            output_files.append(f)
            total_chars += len(f["content"])

    # Also note files that existed in the tree but weren't fetched due to MAX_FILES cap
    skipped_files += [f["path"] for f in all_files[MAX_FILES:]]

    # 4. Build a compact file manifest for agent context
    manifest_lines = [f"  {f['path']} ({f['size']} bytes{', TRUNKERAD' if f.get('truncated') else ''})"
                      for f in output_files]
    if skipped_files:
        manifest_lines.append(f"  [EJ INKLUDERADE: {', '.join(skipped_files[:10])}{'...' if len(skipped_files) > 10 else ''}]")
    file_manifest = (
        f"GRANSKADE FILER ({len(output_files)} av {len(all_files)} matchande, "
        f"{round(total_chars/1000, 1)}k tecken):\n" + "\n".join(manifest_lines)
    )

    return {
        "files": output_files,
        "total_chars": total_chars,
        "truncated": bool(skipped_files),
        "file_count": len(output_files),
        "total_matched": len(all_files),
        "skipped_files": skipped_files,
        "file_manifest": file_manifest,
        "repo": repo,
        "branch": branch,
    }


@app.get("/api/models")
async def get_available_models():
    """Return curated model list — all via OpenRouter."""
    models = [
        # ── Anthropic via OpenRouter ──
        # ── Anthropic ──
        {"id": "anthropic/claude-opus-4.8",      "name": "Claude Opus 4.8",       "provider": "Anthropic", "tier": "best"},
        {"id": "anthropic/claude-sonnet-4.6",    "name": "Claude Sonnet 4.6",     "provider": "Anthropic", "tier": "balanced"},
        {"id": "anthropic/claude-haiku-4.5",     "name": "Claude Haiku 4.5",      "provider": "Anthropic", "tier": "fast"},
        # ── Google (recommended defaults) ──
        {"id": "google/gemini-2.5-pro",          "name": "Gemini 2.5 Pro",        "provider": "Google",    "tier": "best"},
        {"id": "google/gemini-2.5-flash",        "name": "Gemini 2.5 Flash",      "provider": "Google",    "tier": "balanced"},
        {"id": "google/gemini-2.5-flash-lite",   "name": "Gemini 2.5 Flash Lite", "provider": "Google",    "tier": "fast"},
        # ── OpenAI ──
        {"id": "openai/gpt-4o",                  "name": "GPT-4o",                "provider": "OpenAI",    "tier": "best"},
        {"id": "openai/gpt-4.1-mini",            "name": "GPT-4.1 Mini",          "provider": "OpenAI",    "tier": "fast"},
        {"id": "openai/o3",                      "name": "o3",                    "provider": "OpenAI",    "tier": "reasoning"},
        {"id": "openai/o4-mini",                 "name": "o4-mini",               "provider": "OpenAI",    "tier": "reasoning"},
        # ── DeepSeek ──
        {"id": "deepseek/deepseek-r1-0528",      "name": "DeepSeek R1",           "provider": "DeepSeek",  "tier": "reasoning"},
        {"id": "deepseek/deepseek-chat-v3-0324", "name": "DeepSeek V3",           "provider": "DeepSeek",  "tier": "balanced"},
        # ── xAI ──
        {"id": "x-ai/grok-4.20",                 "name": "Grok 4",                "provider": "xAI",       "tier": "best"},
        # ── Meta ──
        {"id": "meta-llama/llama-4-maverick",    "name": "Llama 4 Maverick",      "provider": "Meta",      "tier": "balanced"},
    ]
    s = load_settings()
    has_or = bool(s.get("openrouter_key", "").strip())
    return {
        "models": models,
        "openrouter_available": has_or,
        "agent_ids": list(_DEFAULT_AGENT_MODELS.keys()),
        "defaults": _DEFAULT_AGENT_MODELS,
        "configured": s.get("agent_models", {}),
    }


@app.get("/api/health")
async def health_check():
    """Test all service connections and return status."""
    s = load_settings()
    results = {}

    # ── 1. OpenRouter ──
    or_key = s.get("openrouter_key", "").strip()
    if not or_key:
        results["openrouter"] = {"ok": False, "msg": "API-nyckel saknas"}
    else:
        try:
            import openai as _openai
            or_client = _openai.OpenAI(
                api_key=or_key,
                base_url="https://openrouter.ai/api/v1",
                timeout=15.0,
                default_headers={"HTTP-Referer": "https://prompt-team.local", "X-Title": "Prompt Team"},
            )
            loop = asyncio.get_running_loop()
            resp = await asyncio.wait_for(
                loop.run_in_executor(executor, lambda: or_client.chat.completions.create(
                    model="anthropic/claude-haiku-4.5",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "ping"}]
                )),
                timeout=15.0
            )
            results["openrouter"] = {"ok": True, "msg": f"Ansluten · {resp.model}"}
        except asyncio.TimeoutError:
            results["openrouter"] = {"ok": False, "msg": "Timeout"}
        except Exception as e:
            msg = str(e)
            if "401" in msg or "invalid" in msg.lower():
                msg = "Ogiltig API-nyckel"
            elif "403" in msg:
                msg = "Åtkomst nekad"
            results["openrouter"] = {"ok": False, "msg": msg[:80]}

    # ── 2. GitHub ──
    gh_token = s.get("github_token", "")
    gh_headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if gh_token:
        gh_headers["Authorization"] = f"Bearer {gh_token}"
    try:
        loop = asyncio.get_running_loop()
        gh_resp = await asyncio.wait_for(
            loop.run_in_executor(executor, lambda: httpx.get(
                "https://api.github.com/user" if gh_token else "https://api.github.com/rate_limit",
                headers=gh_headers, timeout=8.0
            )),
            timeout=12.0
        )
        if gh_resp.status_code == 200:
            if gh_token:
                login = gh_resp.json().get("login", "okänd")
                results["github"] = {"ok": True, "msg": f"Inloggad som {login}"}
            else:
                limit = gh_resp.json().get("rate", {}).get("remaining", "?")
                results["github"] = {"ok": True, "msg": f"Publikt API · {limit} anrop kvar (ingen token)"}
        elif gh_resp.status_code == 401:
            results["github"] = {"ok": False, "msg": "Ogiltig GitHub-token"}
        else:
            results["github"] = {"ok": False, "msg": f"HTTP {gh_resp.status_code}"}
    except asyncio.TimeoutError:
        results["github"] = {"ok": False, "msg": "Timeout — GitHub ej nåbart"}
    except Exception as e:
        results["github"] = {"ok": False, "msg": str(e)[:80]}

    # ── 3. Supabase ──
    import socket
    sb_url = _sb_base()  # normalised — strips a trailing /rest/v1 if pasted
    sb_key = s.get("supabase_key", "").strip()
    if not sb_url or not sb_key:
        results["supabase"] = {"ok": False, "msg": "URL eller nyckel saknas"}
    else:
        try:
            # First test DNS resolution
            from urllib.parse import urlparse
            parsed = urlparse(sb_url)
            hostname = parsed.hostname or sb_url
            loop = asyncio.get_running_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(executor, lambda: socket.getaddrinfo(hostname, 443)),
                    timeout=6.0
                )
            except (socket.gaierror, asyncio.TimeoutError):
                results["supabase"] = {"ok": False, "msg": f"DNS-fel: kan inte hitta '{hostname}' — kontrollera URL och nätverksanslutning"}
                raise RuntimeError("dns_fail")

            sb_resp = await asyncio.wait_for(
                loop.run_in_executor(executor, lambda: httpx.get(
                    f"{sb_url}/rest/v1/prompt_sessions?select=id&limit=1",
                    headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}"},
                    timeout=8.0
                )),
                timeout=12.0
            )
            if sb_resp.status_code == 200:
                count = len(sb_resp.json())
                # Read the schema-migration ledger to surface drift (read-only, via REST)
                schema = await loop.run_in_executor(executor, check_supabase_schema)
                results["supabase"] = {
                    "ok": schema["ok"],
                    "msg": f"Ansluten · prompt_sessions finns ({count} rader) · {schema['msg']}",
                    "schema": schema,
                }
            elif sb_resp.status_code == 401:
                results["supabase"] = {"ok": False, "msg": "Ogiltig nyckel — använd Legacy service_role (eyJ...) från API Keys-sidan"}
            elif sb_resp.status_code == 403:
                results["supabase"] = {"ok": False, "msg": "Åtkomst nekad — använd service_role-nyckeln, inte anon"}
            elif sb_resp.status_code == 404:
                results["supabase"] = {"ok": False, "msg": "Tabellen prompt_sessions saknas — kör SQL-scriptet"}
            else:
                results["supabase"] = {"ok": False, "msg": f"HTTP {sb_resp.status_code}: {sb_resp.text[:80]}"}
        except asyncio.TimeoutError:
            if "supabase" not in results:
                results["supabase"] = {"ok": False, "msg": "Timeout — kontrollera Supabase URL"}
        except RuntimeError as e:
            if "dns_fail" not in str(e) and "supabase" not in results:
                results["supabase"] = {"ok": False, "msg": str(e)[:80]}
        except Exception as e:
            if "supabase" not in results:
                results["supabase"] = {"ok": False, "msg": str(e)[:80]}

    # Structured flag so the UI doesn't have to string-match the message
    if "supabase" in results:
        results["supabase"]["configured"] = bool(sb_url and sb_key)

    all_ok = all(v["ok"] for v in results.values())
    return {"ok": all_ok, "services": results}

@app.get("/api/sessions")
async def api_list_sessions(project_id: str = ""):
    # Off the event loop — list_sessions does file I/O (and possibly Supabase)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, list_sessions, project_id)

@app.post("/api/sessions")
async def api_create_session(payload: dict):
    """Save a session directly (used for feedback loop → main project)."""
    import uuid as _uuid
    session_id = payload.get("id") or str(_uuid.uuid4())
    loop = asyncio.get_running_loop()
    save_result = await loop.run_in_executor(executor, save_session,
        session_id,
        payload.get("name", "Session"),
        payload.get("mode", "post"),
        payload.get("input_text", ""),
        payload.get("context", ""),
        payload.get("results", []),
        payload.get("smith", {}),
        payload.get("stats", {}),
        payload.get("project_id", ""),
    )
    return {"ok": save_result["local"], "cloud": save_result["cloud"], "id": session_id}

@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str):
    loop = asyncio.get_running_loop()
    s = await loop.run_in_executor(executor, get_session, session_id)
    if not s:
        return JSONResponse({"error": "Hittades inte"}, status_code=404)
    return s

@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str):
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(executor, delete_session, session_id)
    return {"ok": ok}

@app.get("/api/version")
async def api_version():
    """Returns mtime of index.html — used by browser for live-reload polling."""
    try:
        mtime = (BASE_DIR / "index.html").stat().st_mtime
    except Exception:
        mtime = 0
    return {"mtime": mtime}


if __name__ == "__main__":
    import uvicorn
    # 127.0.0.1 only — 0.0.0.0 exposed the unauthenticated API (and stored keys) to the LAN
    uvicorn.run("app:app", host="127.0.0.1", port=8001, reload=True)
