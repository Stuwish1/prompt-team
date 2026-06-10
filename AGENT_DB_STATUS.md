# AGENT_DB_STATUS — Databasgranskningsrapport
_Genererad: 2026-06-10 | Granskat: app.py (4386 rader), supabase_setup.sql_

---

## SAMMANFATTNING

| # | Allvarlighetsgrad | Problem | Status |
|---|---|---|---|
| DB-01 | 🔴 KRITISK | Saknar `fsync` i alla skrivfunktioner | Ej fixat |
| DB-02 | 🔴 KRITISK | CRLF-endings på Windows (`newline=''` saknas) | Ej fixat |
| DB-03 | 🔴 KRITISK | `sessions.json` korrupt — JSON-fel vid char 3,969,046 | Ej fixat |
| DB-04 | 🔴 KRITISK | `build_queue.json` korrupt — avhuggen mitt i skrivning | Ej fixat |
| DB-05 | 🔠 HÖG | RLS-policy tillåter anon-åtkomst till alla sessioner | Ej fixat |
| DB-06 | 🟠 HÖG | `sessions.json` (4 MB) laddas i sin helhet vid varje läsning | Ej fixat |
| DB-07 | 🟡 MEDIUM | Ingen backup-rotation innan överskrivning | Ej fixat |
| DB-08 | 🟡 MEDIUM | `created_at` skickas som naiv lokal tid till Supabase (`timestamptz`) | Ej fixat |
| DB-09 | 🟢 BRA | Ingen polling mot Supabase — on-demand only | OK |
| DB-10 | 🟢 BRA | DNS-check `_sb_available()` innan varje Supabase-anrop | OK |
| DB-11 | 🟢 BRA | Idempotenta migreringar i supabase_setup.sql | OK |
| DB-12 | 🟢 BRA | schema_migrations-ledger + versionscheck i `/api/health` | OK |

---

## LOKALT JSON-LAGRING

### DB-01 🔴 KRITISK — Saknar `fsync` i alla atomiska skrivfunktioner

**Rotorsak:** Mönstret `tmp.write_text() → tmp.replace()` skyddar mot halvskrivna filer MEN inte mot OS-buffrar som aldrig spolats. På Windows skriver `write_text()` till OS-buffert; om processen kraschar eller strömmen stängs av innan bufferten spolats skrivs en tom eller trunkerad fil.

**Bevis:** `build_queue.json` avhuggen mitt i JSON-objekt. `backlog.json` avslutades med 9 367 noll-bytes (`\x00`) — klassiskt symptom på avbruten skrivning.

**Alla berörda skrivfunktioner (8 st):**

```python
# app.py rad 153 — settings
tmp.write_text(json.dumps(s, ...), encoding="utf-8")
tmp.replace(SETTINGS_FILE)

# rad 390 — backlog
tmp.write_text(json.dumps(items, ...), encoding="utf-8")
tmp.replace(BACKLOG_FILE)

# rad 425 — build queue
tmp.write_text(json.dumps(items, ...), encoding="utf-8")
tmp.replace(BUILD_QUEUE_FILE)

# rad 762 — sessions (_atomic_write)
tmp.write_text(json.dumps(data, ...), encoding="utf-8")
tmp.replace(LOCAL_SESSIONS_FILE)

# rad 2100 — projects
tmp.write_text(json.dumps(data, ...), encoding="utf-8")
tmp.replace(PROJECTS_FILE)

# rad 3275, 3291, 3307, 3388, 3518, 3619 — inline queue-skriv
```

**Fix — extrahera en hjälpfunktion och använd den överallt:**

```python
import os

def _safe_write(path: Path, data: dict) -> None:
    """Atomisk skrivning med fsync — garanterar att data nått disk innan replace."""
    tmp = path.with_suffix(".tmp")
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:  # newline="\n" fixar DB-02
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
```

Ersätt alla `tmp.write_text(...) / tmp.replace(...)` med `_safe_write(path, data)`.

---

### DB-02 🔴 KRITISK — CRLF-endings på Windows

**Rotorsak:** `Path.write_text(encoding='utf-8')` utan `newline=''` aktiverar Pythons universella nyrads-läge. På Windows → varje `\n` skrivs som `\r\n`.

**Bevis:** `sessions.json` innehåller 12 009 `\r\n`-par. Filen är 4 060 219 bytes — uppblåst med ~12 KB jämfört med Unix-version.

**Effekt:**
- Filer klarar sig i Python (som tolkar båda), men externa verktyg (`git diff`, `jq`, `grep`) beter sig konstigt
- Varje git-commit visar hundratals "changed lines" trots att innehållet är oförändrat
- Potentiella parsingproblem i verktyg som kräver LF

**Fix:** Ingår i `_safe_write()` ovan via `newline="\n"`.

---

### DB-03 🔴 KRITISK — `sessions.json` korrupt

**Status:** `json.JSONDecodeError` vid char 3,969,046 (av totalt 4,060,219 chars). Filen saknar avslutande `}`.

**Konsekvens:** Alla 38 sessioner (4 MB data) är otillgängliga tills filen repareras. `_local_load()` returnerar `{}` på undantag → inga sessioner visas i UI.

**Återställningsscript:**

```python
# Kör en gång för att reparera
from pathlib import Path
import json

f = Path("sessions.json")
raw = f.read_bytes().rstrip(b'\x00\r\n ')

# Hitta sista fullständiga entry
decoder = json.JSONDecoder()
fixed = None
for end in range(len(raw), len(raw) - 10000, -1):
    try:
        obj, _ = decoder.raw_decode(raw[:end].decode('utf-8') + '}')
        fixed = obj
        break
    except:
        pass

if fixed:
    import shutil
    shutil.copy(f, f.with_suffix('.json.bak'))
    f.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    print(f"Reparerat: {len(fixed)} sessioner")
```

---

### DB-04 🔴 KRITISK — `build_queue.json` korrupt

**Status:** Trunkerad mitt i JSON-objekt. Slutar med `"detail": "försök 1"\r\n    ` — 2 obundna klamrar.

**Konsekvens:** Alla items i kön försvinner vid nästa serverstart (filen går ej att parse). Pågående byggen markeras inte som `behover_dig`.

**Återställningsscript:**

```python
from pathlib import Path
import json

f = Path("build_queue.json")
raw = f.read_bytes().rstrip(b'\x00\r\n ')

# Försök reparera genom att stänga öppna arrays/objekt
text = raw.decode('utf-8')
# Räkna obalanserade klamrar
opens = text.count('{') - text.count('}')
closes = text.count('[') - text.count(']')
repaired = text + '}' * opens + ']' * closes

try:
    data = json.loads(repaired)
    import shutil
    shutil.copy(f, f.with_suffix('.json.bak'))
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    print(f"Reparerat: {len(data)} items")
except Exception as e:
    print(f"Manuell inspektion krävs: {e}")
```

---

### DB-05 → DB-06 → DB-07 (Lokal lagring — fortsättning)

### DB-06 🟠 HÖG — `sessions.json` laddas i sin helhet vid varje läsning

**Rotorsak:** `_local_load()` och `_local_update()` läser hela filen vid varje anrop. `list_sessions()`, `get_session()`, `delete_session()`, `_migrate_sessions()` — alla kallar `_local_load()`.

**Nuläge:** 4 MB / ~38 sessioner = ~104 KB/session i snitt. Vid 100 sessioner → 10+ MB per API-anrop.

**Rekommendation (kortsiktig):** Lägg till en in-memory-cache med TTL:

```python
_sessions_cache: dict = {}
_sessions_cache_ts: float = 0.0
_SESSIONS_CACHE_TTL = 5.0  # sekunder

def _local_load() -> dict:
    global _sessions_cache, _sessions_cache_ts
    with _sessions_lock:
        now = time.monotonic()
        if _sessions_cache and (now - _sessions_cache_ts) < _SESSIONS_CACHE_TTL:
            return _sessions_cache
        try:
            data = json.loads(LOCAL_SESSIONS_FILE.read_text(encoding="utf-8"))
            _sessions_cache = data
            _sessions_cache_ts = now
            return data
        except Exception:
            return _sessions_cache or {}
```

**Rekommendation (långsiktig):** Migrera till SQLite (`sqlite3` stdlib) — en fil, indexerade queries, ingen O(n)-last.

---

### DB-07 🟡 MEDIUM — Ingen backup-rotation

`_safe_write()` skriver `.tmp` → `.replace()`. Om `.replace()` kraschar (disk full, Windows-fillock) försvinner den tidigare versionen.

**Fix:** Spara `.bak` innan replace:

```python
def _safe_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    bak = path.with_suffix(".bak")
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        shutil.copy2(path, bak)  # backup innan atomisk replace
    tmp.replace(path)
```

---

## SUPABASE-SCHEMA (`supabase_setup.sql`)

### DB-05 🔠 HÖG — RLS-policy tillåter alla (inklusive anon)

**Rotorsak:** Båda tabellerna (`prompt_sessions`, `schema_migrations`) har:

```sql
create policy "Allow all via service role"
  on prompt_sessions for all using (true) with check (true);
```

`using (true)` = alla rader synliga för **alla roller** inklusive `anon`. Intentionen är uppenbart service_role-only (API-nyckeln är en service_role-nyckel) men policyn enforcar inte detta.

**Risk:** En användare med bara Supabase projektets URL + anon-nyckel kan läsa/skriva/radera alla sessioner via Supabase REST-API direkt.

**Fix:**

```sql
-- Ersätt befintliga policies
drop policy if exists "Allow all via service role" on prompt_sessions;
create policy "service_role only"
  on prompt_sessions for all
  to service_role
  using (true) with check (true);

drop policy if exists "Allow all via service role" on schema_migrations;
create policy "service_role only"
  on schema_migrations for all
  to service_role
  using (true) with check (true);
```

Lägg till som **Migration 3** i `supabase_setup.sql` och höj `SUPABASE_SCHEMA_VERSION = 3`.

---

### DB-08 🟡 MEDIUM — `created_at` skickas som naiv lokal tid

**Rotorsak:**

```python
now = datetime.now().isoformat()  # → "2026-06-10T14:23:11.234567" (ingen TZ-info)
payload = {"created_at": now, ...}
httpx.post(_sb_url("prompt_sessions"), json=payload, ...)
```

`prompt_sessions.created_at` är `timestamptz`. Postgres tolkar en naiv timestamp som Supabase-serverns lokala tid (vanligtvis UTC), men det är inte garanterat och kan orsaka felaktig sortering om server och klient är i olika tidszoner.

**Fix:**

```python
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()  # → "2026-06-10T14:23:11.234567+00:00"
```

---

## POSITIVA FYND

### DB-09 🟢 Ingen Supabase-polling

`_sb_available()` anropas endast när en session sparas/hämtas/raderas. Inget bakgrundsloop, ingen periodisk sync. Korrekt arkitektur.

### DB-10 🟢 DNS-check innan Supabase-anrop

`_sb_available()` gör `socket.getaddrinfo()` med 3 sekunders timeout innan varje Supabase-anrop. Förhindrar att appen hänger om Supabase är nere.

### DB-11 🟢 Idempotenta migreringar

Hela `supabase_setup.sql` är säker att köra om:
- `CREATE TABLE IF NOT EXISTS`
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- `INSERT ... ON CONFLICT (version) DO NOTHING`
- `DROP POLICY IF EXISTS` + `CREATE POLICY`

### DB-12 🟢 schema_migrations-ledger

`check_supabase_schema()` läser ledger-tabellen och jämför med `SUPABASE_SCHEMA_VERSION` i app.py. `/api/health` returnerar varning om schemat ligger efter koden. Bra operationellt mönster.

---

## PRIORITERAD ÅTGÄRDSORDNING

### OMEDELBART (innan nästa deploy)

1. **Reparera korrupta filer** — kör återställningsscripten för `sessions.json` och `build_queue.json` lokalt
2. **Implementera `_safe_write()`** — ersätter alla 8+ `write_text/replace`-mönster med fsync + CRLF-fix
3. **Fixa RLS-policy i Supabase** — lägg till Migration 3, höj SUPABASE_SCHEMA_VERSION till 3

### SNART (inom 1-2 sprints)

4. **Fixa `created_at` timezone** — `datetime.now(timezone.utc)`
5. **Sessionsfilcache** — in-memory TTL-cache i `_local_load()`
6. **Backup-rotation** — `.bak` i `_safe_write()`

### LÅNGSIKTIGT

7. **SQLite-migration** — ersätt `sessions.json` med SQLite-databas
8. **Överväg sessions-sharding** — en fil per project_id om SQLite inte är aktuellt

---

## BUILDER-TASKS FÖR ÅTGÄRD

### TASK-DB-01: Lägg till `_safe_write()` och ersätt alla skrivanrop

**Fil:** `app.py`
**Prioritet:** 🔴 KRITISK

**Kod att lägga till** (direkt efter imports, före `_sessions_lock`):

```python
import os, shutil

def _safe_write(path: Path, data: dict) -> None:
    """Atomisk skrivning med fsync och LF-endings. Caller ansvarar för lock."""
    tmp = path.with_suffix(".tmp")
    bak = path.with_suffix(".bak")
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        shutil.copy2(path, bak)
    tmp.replace(path)
```

**Sök-och-ersätt** (alla förekomster):
```python
# GAMMALT
tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(TARGET_FILE)

# NYTT
_safe_write(TARGET_FILE, data)
```

**Acceptanskriterier:**
- `grep -n "write_text" app.py` returnerar NOLL rader (utom eventuell kommentar)
- `python3 -c "import app"` fungerar utan fel
- Skriv en session, kör `file sessions.json` → ska visa LF (inte CRLF)

---

### TASK-DB-02: Migration 3 — Fixa RLS-policy i Supabase

**Fil:** `supabase_setup.sql` + `app.py` (rad `SUPABASE_SCHEMA_VERSION = 2`)

**Kod att lägga till** i `supabase_setup.sql`:

```sql
-- ── Migration 3 — begränsa RLS till service_role only ───────────────────────
drop policy if exists "Allow all via service role" on prompt_sessions;
create policy "service_role only"
  on prompt_sessions for all
  to service_role
  using (true) with check (true);

drop policy if exists "Allow all via service role" on schema_migrations;
create policy "service_role only"
  on schema_migrations for all
  to service_role
  using (true) with check (true);

insert into schema_migrations (version, name)
  values (3, 'RLS begränsad till service_role')
  on conflict (version) do nothing;
```

**I `app.py`:** ändra rad `SUPABASE_SCHEMA_VERSION = 2` → `SUPABASE_SCHEMA_VERSION = 3`

**Acceptanskriterier:**
- Kör `supabase_setup.sql` i Supabase SQL Editor utan fel
- `/api/health` visar `"schema": {"ok": true, "current": 3}`
- Direkt anrop med anon-nyckel mot `prompt_sessions` returnerar 403

---

_Rapport slut. Nästa iteration: kontrollera om ny push finns och uppdatera AGENT_CHATBOX_BUILD.md med TASK-DB-01 och TASK-DB-02._
