# Codebase Audit — Prompt Team
> **Uppdaterad:** 2026-06-10 21:29 — HEAD `eae0f48` på branch `main`

---

## Sammanfattning

| Mått | Värde |
|------|-------|
| app.py | 5 252 rader (TRUNKERAD — syntaxfel rad 5252) |
| index.html | 4 784 rader |
| Endpoints | 39 (17 POST, 16 GET, 3 DELETE, 2 PATCH, 1 on_event) |
| Funktioner totalt | 108 (varav 42 async) |
| Except-block | 58 st |
| load_settings()-anrop | 22 st (cachad, OK) |
| Globala locks | 7 st (threading.Lock) |

**Kritisk status:** app.py är avskuren på rad 5252 — `if __name__ == "__main__"` blocket är ofullständigt.
Python kan inte kompilera filen. Server körs troligen p.g.a. Railway hot-reload, men ny deploy/restart misslyckas.

---

## Teknisk skuld (prioriterad)

### KRITISK

**[TRUNKERING] app.py avskuren på rad 5252**
`host = "0.0.0.0" if os.environ.ge` — raden är avhuggen. SyntaxError verifierat.
Precommit-hooken (INFRA-1) ska fånga detta men filen är ändå trunkerad i senaste commit.
Åtgärd: Lägg till: `host = "0.0.0.0" if os.environ.get("RAILWAY_ENVIRONMENT") else "127.0.0.1"` + `uvicorn.run(app, host=host, port=port)`

---

### HÖG

**[SÄKERHET] subprocess shell=True på 4 ställen**
- Rad 189: `bash_exec`-verktyget — kör agenternas shell-kommandon via `shell=True`. Kommandosträngen kommer från Claude API-svar som kan manipuleras.
- Rad 230, 234: git status/diff i `_execute_chat_tool`
- Rad 4778: `_safe_run_cmd` i builder_stream

`bash_exec` är det allvarligaste — det är avsiktlig sandboxad kodkörning men saknar begränsningar på farliga kommandon (rm -rf, curl till externa URL:er, etc.).

**[STORLEK] delete_session() är ~861 rader**
Funktion rad 1238–2098. En funktion som täcker ~17% av hela backend-koden är omöjlig att testa isolerat och garanterar framtida buggar. Bör delas upp i: `_delete_local()`, `_delete_supabase()`, `_delete_github()`, `_cleanup_session_files()`.

**[STORLEK] review() är ~351 rader (rad 3183)**
Hanterar hela granskarflödet inkl. git-operationer, agent-anrop och Supabase-skrivning. Bör extraheras till separata helpers.

---

### MEDIUM

**[FELHANTERING] 58 generiska except-block**
`except Exception` och `except:` utan specifik typ maskar buggar. Svårt att skilja på förväntade fel (nätverksavbrott) och programmeringsfel (KeyError, AttributeError).

**[STORLEK] builder_stream() är ~219 rader (rad 4937)**
SSE-endpoint som hanterar hela build-loopen inkl. git, agent-anrop, commit, push. Kommentarer (R1–R6) indikerar pågående DRY-arbete — fortsätt det arbetet.

**[DUPLIKERING] load_settings() anropas 22 gånger**
Cachingen via `_settings_cache` fungerar, men anrop är utspridda i hela kodbasen. Dependency injection eller en settings-singleton hade minskat kopplingen.

---

### LÅG

**[DRY] DRY-sprint1 påbörjad men ofullständig**
R1–R6-markeringar finns i builder_stream() (rad 4744–5107). Commit `eae0f48` påstår att `_backlog_write` är DRY:ad. Kontrollera att R2–R6 också är implementerade.

**[DUPLIKERING] _sse() används 23 gånger**
Helper-funktionen finns och används konsekvent — bra. Men SSE-formatet definieras inline på vissa ställen utanför builder_stream.

---

## Löst sedan sist (baserat på PROJECT_STATUS.md + git log)

Commit `eae0f48` (senaste) innehåller:
- ✅ DB-QUEUE-PERSIST: Supabase som persistent queue-backend
- ✅ CHAT-HISTORY-FIX: Chat-historik fix
- ✅ DRY-SPRINT1: R1 (`_backlog_write` extraherad)
- ✅ AGENT-FIX-3: Shell injection i git_commit_push + _chat_sessions GC
- ✅ UX-SPRINT5: alert×7 → inline + confirm×5 → ångra/modal

Totalt 59 godkända items enligt PROJECT_STATUS.md.

---

## Nästa prioriterade åtgärder

1. **Fixa trunkering** — app.py rad 5252 måste kompletteras (5 minuter, KRITISK)
2. **Dela delete_session()** — 861-radsfunktionen är en tidsbomb
3. **bash_exec begränsningar** — blocklista för farliga kommandon (rm -rf, curl, wget till externa)
4. **DRY R2–R6** — slutför pågående sprint
