-- ============================================================================
-- Prompt Team — Supabase schema (versionerad migrationsledger)
-- ============================================================================
-- Kör detta i Supabase SQL Editor:  app.supabase.com → ditt projekt → SQL Editor
--
-- SÄKERT ATT KÖRA OM: hela filen är idempotent (create/alter ... if not exists,
-- insert ... on conflict do nothing). Kör om den när du uppgraderat appen.
--
-- VERSIONSSPÅRNING: tabellen schema_migrations håller reda på vilka migreringar
-- som körts i DENNA databas. Appen läser den via /api/health och varnar om
-- schemat ligger efter koden (konstanten SUPABASE_SCHEMA_VERSION i app.py).
--
-- LÄGGA TILL EN NY MIGRERING:
--   1. Lägg till ett nytt "Migration N"-block längst ner (idempotent DDL).
--   2. Avsluta blocket med:  insert into schema_migrations ... values (N, '...')
--                            on conflict (version) do nothing;
--   3. Höj SUPABASE_SCHEMA_VERSION till N i app.py.
-- Migreringar ska vara additiva och bakåtkompatibla — kör migreringen INNAN ny
-- appkod tas i drift (appen ska kunna starta både före och efter).
-- ============================================================================

-- Ledger: vilka migreringar som applicerats i denna databas
create table if not exists schema_migrations (
  version     integer primary key,
  name        text not null,
  applied_at  timestamptz default now()
);
alter table schema_migrations enable row level security;
drop policy if exists "Allow all via service role" on schema_migrations;
create policy "Allow all via service role"
  on schema_migrations for all using (true) with check (true);


-- ── Migration 1 — bastabell prompt_sessions + index + RLS ───────────────────
create table if not exists prompt_sessions (
  id          text primary key,
  created_at  timestamptz default now(),
  name        text not null,
  mode        text not null,
  input_text  text not null,
  context     text default '',
  results     jsonb default '[]',
  smith       jsonb default '{}',
  stats       jsonb default '{}'
);

create index if not exists idx_prompt_sessions_created_at
  on prompt_sessions (created_at desc);

alter table prompt_sessions enable row level security;
drop policy if exists "Allow all via service role" on prompt_sessions;
create policy "Allow all via service role"
  on prompt_sessions for all using (true) with check (true);

insert into schema_migrations (version, name)
  values (1, 'base prompt_sessions + created_at-index + RLS')
  on conflict (version) do nothing;


-- ── Migration 2 — projekt-stöd: project_id-kolumn + index ────────────────────
-- (Tidigare applicerad manuellt — nu spårad. Idempotent för äldre databaser.)
alter table prompt_sessions
  add column if not exists project_id text default '';

create index if not exists idx_prompt_sessions_project_id
  on prompt_sessions (project_id);

insert into schema_migrations (version, name)
  values (2, 'project_id-kolumn + index på prompt_sessions')
  on conflict (version) do nothing;


-- ── Migration 3 — backlog_items + build_queue_items (Supabase-backup) ───────
CREATE TABLE IF NOT EXISTS backlog_items (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT N