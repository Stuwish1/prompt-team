-- Kör detta en gång i Supabase SQL Editor
-- https://app.supabase.com → ditt projekt → SQL Editor

create table if not exists prompt_sessions (
  id          text primary key,
  created_at  timestamptz default now(),
  name        text not null,
  mode        text not null,
  input_text  text not null,
  context     text default '',
  results     jsonb default '[]',
  smith       jsonb default '{}',
  stats       jsonb default '{}',
  project_id  text default ''
);

-- Om tabellen redan finns, lägg till project_id om den saknas
alter table prompt_sessions
  add column if not exists project_id text default '';

-- Index för snabb filtrering per projekt
create index if not exists idx_prompt_sessions_project_id
  on prompt_sessions (project_id);

create index if not exists idx_prompt_sessions_created_at
  on prompt_sessions (created_at desc);

-- Aktivera Row Level Security (tillåt allt via service role key)
alter table prompt_sessions enable row level security;

-- Ta bort gammal policy om den finns, skapa ny
drop policy if exists "Allow all via service role" on prompt_sessions;

create policy "Allow all via service role"
  on prompt_sessions
  for all
  using (true)
  with check (true);
