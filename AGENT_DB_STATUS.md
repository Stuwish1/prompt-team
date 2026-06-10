# DB-agent Status
**Senast analyserad:** 2026-06-10 (automatisk körning)
_Granskat: app.py (4683 rader), supabase_setup.sql, sessions.json, build_queue.json, backlog.json_

---

## Sammanfattning

| # | Allvarlighetsgrad | Problem | Status |
|---|---|---|---|
| DB-01 | 🔴 KRITISK | Saknar `fsync` i alla skrivfunktioner (20+ ställen) | **Ej fixat** |
| DB-02 | 🔴 KRITISK | CRLF-endings på Windows (`newline=''` saknas) | **Ej fixat** |
| DB-03 | 🔴 KRITISK | `sessions.json` korrupt — ny JSON-fel vid char 395xxx | **Fortfarande korrupt** |
| DB-04 | ✅ LÖST | `build_queue.json` korrupt — trunkerad | **Fixat** |
| DB-05 | 🟠 HÖG | RLS-policy tillåter anon-åtkomst på alla 4 tabeller | **Ej fixat** |
| DB-06 | 🟠 HÖG | `sessions.json` laddas i sin helhet vid varje läsning | **Ej fixat** |
| DB-07 | 🟡 MEDIUM | Ingen backup-rotation innan överskrivning | **Ej fixat** |
| DB-08 | 🟡 MEDIUM | `created_at` skickas som naiv lokal tid till Supabase | **Ej fixat** |
| DB-NEW-1 | 🔴 KRITISK | Chat-verktyg `file_write`/`file_edit` skriver utan lås och utan atomisk write | **Nytt fynd** |
| DB-NEW-2 | 🟠 HÖG | Nya tabeller `backlog_items` + `build_queue_items` har också `using (true)` RLS | **Nytt fynd** |
| DB-NEW-3 | 🟢 BRA | `SUPABASE_SCHEMA_VERSION = 3` + Migration 3 tillagd | **Ny förbättring** |
| DB-NEW-4 | 🟢 BRA | `_sync_to_supabase_async` täcker nu backlog + byggkö | **Ny förbättring** |

---

## Nya fynd sedan sist

### DB-NEW-1 🔴 KRITISK — Chat-verktyg skriver utan lås och utan atomisk write

`_execute_chat_tool()` i chattboxen låter AI-agenten skriva direkt till filer utan varken lås eller `.tmp → .replace()`-mönster:

```python
# app.py rad 206–210 (file_write)
elif name == "file_write":
    p = _safe_path(input_data["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(input_data["content"], encoding="utf-8")  # ← direkt write, ingen atomicitet

# app.py rad 212–223 (file_edit)
elif name == "file_edit":
    p = _safe_path(input_data["path"])
    content = p.read_text(encoding="utf-8")
    ...
    p.write_text(content.replace(old_s, new_s, 1), encoding="utf-8")  # ← direkt write
```

**Risk:** AI-agenten kan skriva `sessions.json`, `build_queue.json` eller `backlog.json` mitt i att serverns egna write-lock håller filen. Dessutom: om servern kraschar under `file_write` av en stor fil (t.ex. `app.py`) → trunkerad fil.

**Fix:** Använd `_safe_write()` (när den implementeras per DB-01), och kräv att `file_write` skriver till `.tmp` + `os.replace()`. För att förhindra att AI:n skriver till kärndata-filer direkt kan man lägga till en blocklist: `sessions.json`, `build_queue.json`, `backlog.json` bör aldrig skrivas via chat-verktyget.

---

### DB-NEW-2 🟠 HÖG — Nya tabeller saknar service_role-only RLS

Migration 3 i `supabase_setup.sql` skapar `backlog_items` och `build_queue_items` med:

```sql
CREATE POLICY "Allow all via service role"
  ON backlog_items FOR ALL USING (true) WITH CHECK (true);
```

`USING (true)` = anon-åtkomst tillåts. Samma RLS-problem som de befintliga tabellerna. Alla fynd och byggkö-items är läsbara för vem som helst med projektets URL.

---

## Fortfarande relevanta fynd (ej åtgärdade)

### DB-01 🔴 — Saknar `fsync` (alla 20+ skrivfunktioner)

`_safe_write()` är **inte implementerad**. Alla skrivfunktioner använder fortfarande `write_text()` utan fsync:

```
rad 344  — save_settings()
rad 585  — backlog_add_items()
rad 623  — _queue_write()
rad 975  — _atomic_write() / sessions
rad 2342 — _projects_write()
rad 3599, 3615, 3631, 3712, 3842, 3944, 4043 — inline backlog-skriv (7 st)
```

Totalt: **20+ `write_text`-anrop** utan fsync. `_safe_write()` måste implementeras och ersätta samtliga.

---

### DB-02 🔴 — CRLF-endings

Ingen `newline="\n"` på något enda `write_text`-anrop. Alla JSON-filer skrivs med `\r\n` på Windows. Ingår i DB-01-fix via `_safe_write()`.

---

### DB-03 🔴 — `sessions.json` fortfarande korrupt

Verifierat med `json.loads()` — filen är korrupt vid **char 395xxx** (ny position, troligen ny korruption efter förra rapporten). Tidigare session-data kan ha gått förlorad.

Kör återställningsscriptet från föregående rapport för att reparera filen. Permanent fix kräver DB-01 (`fsync`).

---

### DB-05 🟠 — RLS tillåter anon-åtkomst (alla 4 tabeller)

`prompt_sessions`, `schema_migrations`, `backlog_items`, `build_queue_items` har alla `USING (true)`. Behöver migreras till `TO service_role`.

**Migration 4** att lägga till i `supabase_setup.sql`:

```sql
-- ── Migration 4 — begränsa RLS till service_role only ───────────────────
do $$ begin
  drop policy if exists "Allow all via service role" on prompt_sessions;
  drop policy if exists "Allow all via service role" on schema_migrations;
  drop policy if exists "Allow all via service role" on backlog_items;
  drop policy if exists "Allow all via service role" on build_queue_items;
  create policy "service_role only" on prompt_sessions for all to service_role using (true) with check (true);
  create policy "service_role only" on schema_migrations for all to service_role using (true) with check (true);
  create policy "service_role only" on backlog_items for all to service_role using (true) with check (true);
  create policy "service_role only" on build_queue_items for all to service_role using (true) with check (true);
end $$;
insert into schema_migrations (version, name)
  values (4, 'RLS begränsad till service_role on all tables')
  on conflict (version) do nothing;
```

Höj `SUPABASE_SCHEMA_VERSION = 4` i `app.py`.

---

### DB-06 🟠 — `sessions.json` laddas i sin helhet vid varje läsning

Inga ändringar sedan sist. In-memory TTL-cache saknas fortfarande.

---

### DB-07 🟡 — Ingen backup-rotation

`.bak`-fil sparas inte innan atomic replace. Ingår i DB-01-fix via utökad `_safe_write()`.

---

### DB-08 🟡 — Naiv lokal tid till Supabase

`datetime.now().isoformat()` används på rad 1145 och 1106 (och många fler) utan timezone-info. Fix: `datetime.now(timezone.utc).isoformat()`.

---

## Löst sedan sist

### DB-04 ✅ — `build_queue.json` reparerad
`build_queue.json` parsar nu korrekt (list, 50 items). Troligen manuellt reparerat eller överskrevet.

### DB-NEW-3 ✅ — Migration 3 + SUPABASE_SCHEMA_VERSION = 3
`supabase_setup.sql` har nu Migration 3 som skapar `backlog_items` och `build_queue_items`. `SUPABASE_SCHEMA_VERSION` är höjt till 3 i `app.py`. Schema-check i `/api/health` stämmer nu.

### DB-NEW-4 ✅ — Supabase-sync för backlog och byggkö
`_sync_to_supabase_async()` anropas nu från `backlog_add_items()` (rad 589) och `_queue_write()` (rad 626) för fire-and-forget backup till de nya tabellerna. Korrekt arkitektur.

---

## Prioriterad åtgärdsordning

### OMEDELBART

1. **Reparera `sessions.json`** — kör återställningsscript (se förra rapporten). Data förlorad om ej gjort.
2. **Implementera `_safe_write()`** — ersätt alla 20+ `write_text`-anrop. Stoppar ny korruption.
3. **Blockera chat-verktyget från kärndata** — `file_write`/`file_edit` ska inte kunna skriva `sessions.json`, `build_queue.json`, `backlog.json`.

### SNART

4. **Migration 4 — fixa RLS på alla 4 tabeller**
5. **Fixa `created_at` timezone** — `datetime.now(timezone.utc)`
6. **Sessionsfilcache** — in-memory TTL-cache i `_local_load()`

### LÅNGSIKTIGT

7. **SQLite-migration** — ersätt `sessions.json` med SQLite
