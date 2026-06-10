# Project Status
**Senast uppdaterad:** 2026-06-11T07:18 (projektledaren-auto)

## Senast godkänt
- KID-SPRINT1: Barnvänliga felmeddelanden + verktygsnamn + git-rubrik i chat — klar

## Klart totalt (godkänt av granskaren) — 65 st
- ✅ P1: Saknade las — race conditions
- ✅ P1: Input-validering + path traversal
- ✅ P1-A: Återställ stale byggs-items vid serveromstart
- ✅ P1-B: Hemlighetsvakten som hårt block
- ✅ P1-C: Säkerhetsagenter alltid i snabbläge
- ✅ P1-D: Sessions-paginering
- ✅ P1-E: _RUN_RESULTS till disk
- ✅ P1-F: Semaphore på /api/review
- ✅ P1-G: Stäng av reload=True i produktion
- ✅ P1-H: Supabase-backup
- ✅ P1-I: Återlägg interim_result*.json i .gitignore
- ✅ P1-K: 409-skydd mot dubbla anrop
- ✅ P1-L: get_backlog() läser utan lås (KRITISK)
- ✅ P1-M: PATCH /api/build-queue storleksgräns
- ✅ P1-N: POST /api/build-queue tom project_id
- ✅ P1-O: GET /api/build-queue utan lås
- ✅ P1-P: build_queue_review() TOCTOU
- ✅ P1-Q: backlog_to_spec() utan lås
- ✅ CHAT-1: Backend /api/chat med SSE-streaming
- ✅ CHAT-2: Frontend chattflik
- ✅ P2-A: Chatt-UI slide-in panel
- ✅ P2-B: Chatt-backend + SSE-streaming
- ✅ P2-C: Auto-dispatch — startBuild() postar spec
- ✅ P2-D: GitHub push-endpoint
- ✅ P3-A: Projektprofiler på servern
- ✅ P3-G: CI-gate med GitHub Actions
- ✅ P3-H: Historikpanel — visa totalt + sökfält
- ✅ P3-M: Återinför _repair_truncated_json
- ✅ P3-N: Återinför vag-input-gate
- ✅ P3-Q: GitHub-filhämtning i batchar
- ✅ P3-R: Återinför kontrolleraBuild()
- ✅ P3-S: Skärp backlog-dedup i _is_same_issue()
- ✅ P3-T: _progress_set() GC → bakgrundsjobb
- ✅ BUG: backlog.json korrupt — null-byte overflow
- ✅ BUG: app.py SyntaxError rad 4807
- ✅ INFRA-1: Precommit-hook mot filtrunkering
- ✅ AGENT-FIX-1: review_started_at-läcka + _chat_sessions GC + chat_id-validering
- ✅ CHATBOX-BACKEND: SSE endpoint /api/builder/stream/{item_id} + BUILDER_TOOLS
- ✅ CHATBOX-FRONTEND: #builderPanel HTML/CSS/JS — chat-panel för byggagenten
- ✅ UX-SPRINT1: UX-1 (alert→inline) + UX-6 (queueDelete ångra) + UX-16 (showToast HTML)
- ✅ BUG/SEC-1 + BUG-5 + AGENT_DISPLAY_NAMES: path traversal, switchView CSS, 10 agentnamn
- ✅ P4-A+B+C: Teknisk skuld — httpx-import, settings-lock, dead code
- ✅ P4-D+E: Hälsokontroll cached klient + normalisera modellsträngar
- ✅ P4-F: GitHub inbound webhook
- ✅ BUG-6: Uppskjutna imports — flytta till modulnivå
- ✅ WEBHOOK-FIX: GitHub webhook triggar aldrig auto-granskning
- ✅ UX-SPRINT2: UX-AL (local_path UI) + UX-4 (tom kö CTA) + UX-10 (modeHelp per läge) + UX-2 (barnv