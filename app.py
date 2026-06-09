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

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_settings_lock = threading.Lock()

BASE_DIR = Path(__file__).parent
SETTINGS_FILE = BASE_DIR / "settings.json"

# ──────────────────────────────────────────────
# SETTINGS
# ──────────────────────────────────────────────

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"api_key": "", "model": "claude-sonnet-4-6", "supabase_url": "", "supabase_key": "", "github_token": "", "self_repo": "", "self_branch": "main"}


def save_settings(s: dict):
    with _settings_lock:
        SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def get_client():
    key = load_settings().get("api_key", "")
    if not key:
        return None
    return anthropic.Anthropic(api_key=key, timeout=120.0)


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
        LOCAL_SESSIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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
            LOCAL_SESSIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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

def _sb_url(path: str) -> str:
    s = load_settings()
    base = s.get("supabase_url", "").strip().rstrip("/")
    return f"{base}/rest/v1/{path}"

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

def auto_name(input_text: str) -> str:
    words = input_text.strip().split()[:7]
    name = " ".join(words)
    if len(name) > 60:
        name = name[:57] + "..."
    date_str = datetime.now().strftime("%d %b")
    return f"{name} · {date_str}"

def save_session(session_id: str, name: str, mode: str, input_text: str,
                 context: str, results: list, smith: dict, stats: dict,
                 project_id: str = "") -> bool:
    now = datetime.now().isoformat()
    payload = {
        "id": session_id, "name": name, "mode": mode,
        "created_at": now, "input_text": input_text,
        "context": context, "results": results, "smith": smith, "stats": stats,
        "project_id": project_id,
    }
    # Always save locally first (instant, reliable, race-safe)
    try:
        _local_update(session_id, payload)
    except Exception as e:
        logger.warning("Local session save failed: %s", e)

    # Try Supabase in background if available
    if _sb_available():
        try:
            headers = _sb_headers()
            r = httpx.post(
                _sb_url("prompt_sessions"), json=payload,
                headers={**headers, "Prefer": "resolution=merge-duplicates,return=minimal"},
                timeout=10.0
            )
            if r.status_code in (200, 201):
                logger.info("Session also saved to Supabase")
        except Exception as e:
            logger.warning("Supabase save failed (local backup exists): %s", e)
    return True

def list_sessions(project_id: str = "") -> list:
    # Fall back to local (Supabase DNS unreliable)
    try:
        data = _local_load()
        sessions = [
            {
                "id": v["id"], "name": v["name"], "mode": v["mode"],
                "created_at": v.get("created_at", ""),
                "project_id": v.get("project_id", ""),
            }
            for v in data.values()
            if (not project_id) or v.get("project_id", "") == project_id
        ]
        sessions.sort(key=lambda x: x["created_at"], reverse=True)
        return sessions[:50]
    except Exception:
        return []

def get_session(session_id: str) -> dict | None:
    if _sb_available():
        try:
            headers = _sb_headers()
            r = httpx.get(
                _sb_url(f"prompt_sessions?id=eq.{session_id}&select=*"),
                headers=headers, timeout=10.0
            )
            if r.status_code == 200:
                data = r.json()
                return data[0] if data else None
        except Exception as e:
            logger.warning("Supabase get failed, using local: %s", e)
    # Fall back to local
    try:
        data = _local_load()
        return data.get(session_id)
    except Exception:
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

PRE_BUILD_AGENTS = [
    {
        "id": "architecture",
        "name": "Arkitekten",
        "emoji": "🏗️",
        "phase": "pre",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är en erfaren enterprise-arkitekt. Granska följande beskrivning strikt utifrån "
            "arkitekturprinciper: separation of concerns, single responsibility, rätt designmönster, "
            "minimala och korrekt riktade beroenden samt anpassning till befintlig systemarkitektur. "
            "Identifiera konkret vilka principer som riskerar att brytas. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "ux",
        "name": "UX-agenten",
        "emoji": "🎨",
        "phase": "pre",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är UX-agenten. Granska beskrivningen ur ett användarupplevelseperspektiv. "
            "Fokusera på: logiska flöden, loading states, empty states, felmeddelanden för användaren, "
            "bekräftelsedialoger för destruktiva actions, inga döda ändar. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "database",
        "name": "Databasagenten",
        "emoji": "🗄️",
        "phase": "pre",
        "model": "claude-haiku-4-5-20251001",
        "system": (
            "Du är en senior databasarkitekt. Granska beskrivningen för datalagrings-aspekter. "
            "Kontrollera: normalisering, index-behov, foreign keys, rätt datatyper, migrationsstrategi, "
            "inga råa SQL-strängar. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
]

POST_BUILD_AGENTS = [
    {
        "id": "code_quality",
        "name": "Kodkvalitet",
        "emoji": "📋",
        "phase": "post",
        "model": "claude-haiku-4-5-20251001",
        "system": (
            "Du är kodkvalitets-granskare. Granska ENBART kodstil och kvalitetsstandarder: "
            "engelska identifierare och variabelnamn, beskrivande namn, förklarande kommentarer, "
            "frånvaro av magic numbers, konsekvent namngivningskonvention (camelCase/snake_case). "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "security",
        "name": "Säkerheten",
        "emoji": "🔒",
        "phase": "post",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är en senior applikationssäkerhetsexpert (OWASP Top 10). Granska koden systematiskt. "
            "Kontrollera: SQL injection, XSS, exponerade API-nycklar, auth-kontroller, CORS, "
            "input-validering, HTTPS, security headers. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "performance",
        "name": "Prestanda",
        "emoji": "⚡",
        "phase": "post",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är en prestandagranskare. Identifiera: N+1 queries, onödiga re-renders, "
            "för stora bundles, saknad caching, tunga synkrona operationer, minneläckor, "
            "ineffektiva datastrukturer, saknade databasindex, lazy loading saknas. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "visual",
        "name": "Visuell agent",
        "emoji": "🖼️",
        "phase": "post",
        "model": "claude-haiku-4-5-20251001",
        "system": (
            "Du är visuell design-granskare. Kontrollera: design tokens används (inga hårdkodade hex), "
            "typografi följer skalan, spacing-system (4/8px), komponentbibliotek används, "
            "inga statiska inline-stilar, dark mode fungerar via tokens, kontrast WCAG AA. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "accessibility",
        "name": "Tillgänglighet",
        "emoji": "♿",
        "phase": "post",
        "model": "claude-haiku-4-5-20251001",
        "system": (
            "Du är WCAG 2.1 AA-expert. Granska: ARIA-labels, tangentbordsnavigation, "
            "focus-states, kontrast 4.5:1 för text / 3:1 för UI, alt-text på bilder, "
            "formulärlabels, rubriker i hierarki, landmarks, inga keyboard traps. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "mobile",
        "name": "Mobilagenten",
        "emoji": "📱",
        "phase": "post",
        "model": "claude-haiku-4-5-20251001",
        "system": (
            "Du är mobilexpert. Kontrollera: viewport meta, touch targets ≥44px, "
            "inga hover-only interaktioner, responsiv layout 320-768px, "
            "ingen horisontell scroll, läsbar text utan zoom, korrekt inputmode på formulär. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "testing",
        "name": "Test-agenten",
        "emoji": "🧪",
        "phase": "post",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är QA-ingenjör. Granska: happy path testad, felfall och undantag testas, "
            "edge cases täckta, input-validering testad, mocks används korrekt, "
            "tester oberoende av varandra, testbar kod (löst kopplad), beskrivande testnamn. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "api",
        "name": "API-agenten",
        "emoji": "🔌",
        "phase": "post",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är API-designexpert. Kontrollera: RESTful namngivning (substantiv plural, kebab-case), "
            "rätt HTTP-metoder, konsekvent felformat, korrekta statuskoder, versionering, "
            "auth på alla skyddade routes, inga känsliga fält i responses, paginering. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "duplication",
        "name": "Dubbelkollaren",
        "emoji": "🔁",
        "phase": "post",
        "model": "claude-haiku-4-5-20251001",
        "system": (
            "Du är DRY-expert. Sök aktivt efter: identisk logik på flera ställen (>8 rader), "
            "komponenter återskapade trots att de finns, saknade imports till befintliga utils, "
            "konstanter definierade på flera ställen, copy-paste-kod. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "error_handling",
        "name": "Felhantering",
        "emoji": "🚨",
        "phase": "post",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är robusthetsexpert. Kontrollera: alla async-anrop har try/catch, "
            "fel swallowas inte tyst, stacktraces exponeras ej mot användaren, "
            "användarvänliga felmeddelanden, retry-logik på kritiska anrop, timeout-hantering. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "documentation",
        "name": "Dokumentation",
        "emoji": "📝",
        "phase": "post",
        "model": "claude-haiku-4-5-20251001",
        "system": (
            "Du är dokumentationsgranskare. Kontrollera: JSDoc/docstrings på publika funktioner, "
            "README uppdaterad, komplexa algoritmer förklarade, API-endpoints dokumenterade, "
            "inga TODOs utan issue-nummer, exporterade typer kommenterade. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "scalability",
        "name": "Skalbarhet",
        "emoji": "📈",
        "phase": "post",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är DevOps/SRE-expert. Kontrollera: stateless services, inga hårdkodade URLs/portar, "
            "config från env variables, /health och /ready endpoints, graceful shutdown (SIGTERM), "
            "connection pooling, logging till stdout i JSON-format. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "data_privacy",
        "name": "Dataskydd",
        "emoji": "🛡️",
        "phase": "post",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är GDPR-expert. Kontrollera: PII inte i klartext i loggar, persondata krypterad, "
            "samtycke inhämtat korrekt, rätt att radera implementerat, "
            "data delas ej med tredje part utan grund, cookie-consent blockerar icke-nödvändiga cookies. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "dependencies",
        "name": "Beroenden",
        "emoji": "📦",
        "phase": "post",
        "model": "claude-haiku-4-5-20251001",
        "system": (
            "Du är supply chain security-expert. Kontrollera: inga kända CVE:er, "
            "lock-fil committad, inga oanvända beroenden i production, "
            "devDependencies korrekt kategoriserade, tree-shaking möjlig, "
            "beroenden från betrodda registries, licenser kompatibla. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "i18n",
        "name": "Språk & i18n",
        "emoji": "🌍",
        "phase": "post",
        "model": "claude-haiku-4-5-20251001",
        "system": (
            "Du är i18n/l10n-expert. Kontrollera: inga hårdkodade UI-strängar, "
            "datum/tid/valuta formaterade med locale-aware API:er, RTL-stöd ej brutet, "
            "translation-keys konsekvent namngivna, pluralisering via ramverkets API. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
    {
        "id": "frontend",
        "name": "Frontend-agenten",
        "emoji": "💻",
        "phase": "post",
        "model": "claude-sonnet-4-6",
        "system": (
            "Du är senior frontend-granskare (React/Vue/vanilla). Kontrollera: "
            "komponentstruktur logisk (SRP), state-hantering inte överdrivet komplex, "
            "inga direkta DOM-manipulationer utanför ramverket, props väldefinierade och typsäkra, "
            "event listeners rensas upp, tunga komponenter lazy-laddas. "
            "Returnera ENBART JSON: "
            '{\"status\":\"GODKÄND\"/\"UNDERKÄND\",\"findings\":[\"...\"],\"severity\":\"LOW\"/\"MEDIUM\"/\"HIGH\",\"suggestions\":[\"...\"]}'
        ),
    },
]

PROMPT_SMITH = {
    "id": "prompt_smith",
    "name": "Promptsmeden",
    "emoji": "✍️",
    "phase": "synth",
        "model": "claude-sonnet-4-6",
    "system": (
        "Du är Promptsmeden. Du tar emot en idé/kod + agenternas feedback och returnerar ALLTID ett av två JSON-format.\n\n"

        "FORMAT A — när du har TILLRÄCKLIG information:\n"
        '{ "type": "prompt", "content": "## CONTEXT\\n...\\n\\n## TASK\\n...\\n\\n## CONSTRAINTS\\n...\\n\\n## REVIEW REQUIREMENTS\\n...\\n\\n## ASSUMPTIONS\\n...\\n\\n## ACCEPTANCE CRITERIA\\n[ ] ...\\n" }\\n\\n'

        "FORMAT B — när VIKTIG information SAKNAS och du inte kan skriva en meningsfull prompt:\n"
        '{ "type": "questions", "intro": "Beskriv lite mer...", "questions": [ { "id": "q1", "text": "...", "options": ["...", "...", "Annat"] } ] }\\n\\n'

        "REGLER FÖR FORMAT B — dynamiska, kontextanpassade frågor:\n"
        "Generera 1-4 frågor ENBART baserat på vad som faktiskt saknas i JUST DENNA idé. "
        "Analysera idén och agentfeedbacken och identifiera de specifika informationsluckor som gör det omöjligt att skriva en precis prompt. "
        "Frågor och alternativ måste vara direkt relevanta för den specifika kontexten — ALDRIG generiska webb-mallar. "
        "Exempel: mobilapp → fråga om iOS/Android/cross-platform, inte webbstack. "
        "Exempel: CLI-verktyg → fråga om språk och distribution, inte databas. "
        "Exempel: om stack är uppenbar → hoppa stack-frågan. "
        "Inkludera alltid 'Annat / vet ej' som sista alternativ. "
        "Använd svenska om originalidén är på svenska.\n\n"

        "BESLUTSREGEL:\n"
        "FORMAT B ENBART om minst ett av dessa gäller: "
        "(1) Systemets syfte är så vagt att prompt inte kan specificera beteende, "
        "(2) Plattform/miljö är oklar och avgör tekniska constraints, "
        "(3) Målgruppen är oklar och påverkar designbeslut väsentligt. "
        "I alla andra fall: FORMAT A med rimliga antaganden under ## ASSUMPTIONS. "
        "En tydlig prompt med antaganden är alltid bättre än fler frågor.\n\n"

        "Returnera ENBART JSON, ingen annan text. "
        "I FORMAT A: content på engelska, acceptance criteria på svenska om originalet är på svenska."
    ),
}

ALL_AGENTS = {a["id"]: a for a in PRE_BUILD_AGENTS + POST_BUILD_AGENTS + [PROMPT_SMITH]}


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
            # Try ast for single-quote dicts
            try:
                import ast as _ast
                obj = _ast.literal_eval(candidate)
            except Exception:
                continue
        if not isinstance(obj, dict):
            continue
        if obj.get("status") not in ("GODKÄND", "UNDERKÄND"):
            continue
        obj.setdefault("findings", [])
        obj.setdefault("severity", "MEDIUM")
        obj.setdefault("suggestions", [])
        if not isinstance(obj["findings"], list):
            obj["findings"] = [str(obj["findings"])]
        if not isinstance(obj["suggestions"], list):
            obj["suggestions"] = [str(obj["suggestions"])]
        obj.pop("_error", None)
        return obj
    return FALLBACK


_RETRY_SUFFIX = (
    "\n\nSVARA ENBART med detta JSON-format (inga andra ord):\n"
    '{"status":"GODKÄND"|"UNDERKÄND","findings":["..."],"severity":"LOW"|"MEDIUM"|"HIGH","suggestions":["..."]}'
)

# ──────────────────────────────────────────────
# SYSTEM REFERENCE — injected into every agent
# ──────────────────────────────────────────────
_SYSTEM_REFERENCE = (
    "\n\n[SYSTEMREFERENS] Detta system är byggt enligt Prompt Teams arkitektur: "
    "FastAPI-backend, vanilla JS-frontend (inga ramverk), lokalt sessions.json för lagring, "
    "GitHub read-only för kodläsning. Beakta dessa constraints i din granskning."
)


def run_agent(agent: dict, user_input: str, model: str, client) -> dict:
    """Run a single agent synchronously. Retries once with explicit JSON reminder on parse failure."""
    agent_model = agent.get("model", model)

    def _call(system_extra="") -> str:
        resp = client.messages.create(
            model=agent_model,
            max_tokens=450,
            system=agent["system"] + _SYSTEM_REFERENCE + system_extra,
            messages=[{"role": "user", "content": user_input}],
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


def run_prompt_smith(original_input: str, agent_results: list, model: str, client) -> dict:
    model = "claude-sonnet-4-6"  # Promptsmeden always uses Sonnet
    """Run Promptsmeden. Returns {type: prompt|questions, ...}."""
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
        response = client.messages.create(
            model=model,
            max_tokens=800,
            system=PROMPT_SMITH["system"],
            messages=[{"role": "user", "content": combined}],
        )
        raw = response.content[0].text if response.content else ""
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
        return {"type": "prompt", "content": f"Kunde inte generera prompt: {e}"}


# ──────────────────────────────────────────────
# ENDPOINTS
# ──────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/settings")
async def get_settings():
    s = load_settings()
    key = s.get("api_key", "")
    if key:
        s["api_key"] = "sk-***" + key[-4:]
    return s


@app.post("/api/settings")
async def post_settings(payload: dict):
    s = load_settings()
    if "api_key" in payload and payload["api_key"] and not payload["api_key"].startswith("sk-***"):
        s["api_key"] = payload["api_key"]
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


@app.post("/api/review")
async def review(payload: dict):
    """
    payload: {
        mode: "pre" | "post" | "both",
        input_text: str,       # idea description or code
        context: str           # optional extra context
    }
    """
    mode = payload.get("mode", "pre")
    input_text = payload.get("input_text", "").strip()
    context = payload.get("context", "").strip()
    project_id = payload.get("project_id", "")

    if not input_text:
        return JSONResponse({"error": "Ingen text angiven."}, status_code=400)

    s = load_settings()
    client = get_client()
    if not client:
        return JSONResponse(
            {"error": "API-nyckel saknas. Gå till Inställningar och lägg till din Anthropic API-nyckel."},
            status_code=400,
        )

    model = s.get("model", "claude-sonnet-4-6")

    # Select agents based on mode
    if mode == "pre":
        agents = PRE_BUILD_AGENTS
    elif mode == "post":
        agents = POST_BUILD_AGENTS
    else:  # both
        agents = PRE_BUILD_AGENTS + POST_BUILD_AGENTS

    # Build full input for agents
    full_input = input_text
    if context:
        full_input = f"KONTEXT:\n{context}\n\n{'BESKRIVNING/KOD' if mode == 'post' else 'IDÉ ATT GRANSKA'}:\n{input_text}"

    # Run all agents in parallel with per-agent timeout
    loop = asyncio.get_running_loop()

    async def run_with_timeout(agent):
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(executor, run_agent, agent, full_input, model, client),
                timeout=95.0
            )
        except asyncio.TimeoutError:
            return {
                "id": agent["id"], "name": agent["name"],
                "emoji": agent["emoji"], "phase": agent["phase"],
                "status": "FEL", "findings": ["Timeout — agenten svarade inte inom 95s"],
                "severity": "HIGH", "suggestions": [], "raw": "", "error": "timeout"
            }

    try:
        results = list(await asyncio.wait_for(
            asyncio.gather(*[run_with_timeout(a) for a in agents]),
            timeout=150.0
        ))
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Granskningen tog för lång tid (>150s). Försök med färre agenter."}, status_code=504)

    # Run Promptsmeden last with all results
    smith_result = await loop.run_in_executor(
        executor, run_prompt_smith, input_text, results, model, client
    )

    # Summary stats
    approved = sum(1 for r in results if r["status"] == "GODKÄND")
    rejected = sum(1 for r in results if r["status"] == "UNDERKÄND")
    errors = sum(1 for r in results if r["status"] == "FEL")

    session_id = str(uuid.uuid4())
    session_name = auto_name(input_text)
    stats_dict = {"total": len(results), "approved": approved, "rejected": rejected, "errors": errors}

    # Auto-save (non-blocking best-effort)
    loop.run_in_executor(executor, save_session,
        session_id, session_name, mode, input_text, context,
        results, smith_result, stats_dict, project_id
    )

    return {
        "session_id": session_id,
        "session_name": session_name,
        "results": results,
        "smith": smith_result,
        "final_prompt": smith_result.get("content", "") if smith_result.get("type") == "prompt" else "",
        "stats": stats_dict,
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

@app.post("/api/github/fetch")
async def github_fetch(payload: dict):
    """
    payload: { repo: "owner/repo", branch: "main", path: "" }
    Returns: { files: [{path, content, size}], total_chars, truncated }
    """
    repo = payload.get("repo", "").strip().removeprefix("https://github.com/").lstrip("/")
    branch = payload.get("branch", "main").strip() or "main"
    path_filter = payload.get("path", "").strip().lstrip("/")

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
    all_files = [
        item for item in tree_data.get("tree", [])
        if item["type"] == "blob"
        and any(item["path"].endswith(ext) for ext in INCLUDE_EXTENSIONS)
        and not any(excl in item["path"].split("/") for excl in EXCLUDE_DIRS)
        and (not path_filter or item["path"].startswith(path_filter))
        and item.get("size", 0) < 100_000  # skip huge files
    ]

    # Sort: smaller files first, prioritize src/
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
            return {"path": item["path"], "content": content[:MAX_FILE_CHARS], "size": len(content)}
        except Exception:
            return None

    file_results = await asyncio.gather(*[fetch_file(f) for f in selected])
    files = [f for f in file_results if f]

    # 3. Build combined code string (with file headers)
    total_chars = 0
    output_files = []
    for f in files:
        if total_chars + len(f["content"]) > MAX_TOTAL_CHARS:
            break
        output_files.append(f)
        total_chars += len(f["content"])

    return {
        "files": output_files,
        "total_chars": total_chars,
        "truncated": len(files) > len(output_files),
        "file_count": len(output_files),
        "repo": repo,
        "branch": branch,
    }


@app.get("/api/health")
async def health_check():
    """Test all service connections and return status."""
    s = load_settings()
    results = {}

    # ── 1. Anthropic ──
    api_key = s.get("api_key", "")
    if not api_key:
        results["anthropic"] = {"ok": False, "msg": "API-nyckel saknas"}
    else:
        try:
            client = anthropic.Anthropic(api_key=api_key, timeout=10.0)
            loop = asyncio.get_running_loop()
            resp = await asyncio.wait_for(
                loop.run_in_executor(executor, lambda: client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "ping"}]
                )),
                timeout=15.0
            )
            results["anthropic"] = {"ok": True, "msg": f"Ansluten · {resp.model}"}
        except asyncio.TimeoutError:
            results["anthropic"] = {"ok": False, "msg": "Timeout — kontrollera nyckel"}
        except Exception as e:
            msg = str(e)
            if "401" in msg or "invalid" in msg.lower():
                msg = "Ogiltig API-nyckel"
            elif "403" in msg:
                msg = "Åtkomst nekad"
            results["anthropic"] = {"ok": False, "msg": msg[:80]}

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
    sb_url = s.get("supabase_url", "").strip().rstrip("/")
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
                results["supabase"] = {"ok": True, "msg": f"Ansluten · prompt_sessions finns ({count} rader synliga)"}
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

    all_ok = all(v["ok"] for v in results.values())
    return {"ok": all_ok, "services": results}

@app.get("/api/sessions")
async def api_list_sessions(project_id: str = ""):
    return list_sessions(project_id)

@app.post("/api/sessions")
async def api_create_session(payload: dict):
    """Save a session directly (used for feedback loop → main project)."""
    import uuid as _uuid
    session_id = payload.get("id") or str(_uuid.uuid4())
    ok = save_session(
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
    return {"ok": ok, "id": session_id}

@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str):
    s = get_session(session_id)
    if not s:
        return JSONResponse({"error": "Hittades inte"}, status_code=404)
    return s

@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str):
    ok = delete_session(session_id)
    return {"ok": ok}
