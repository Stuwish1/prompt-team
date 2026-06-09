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
  stats       jsonb default '{}'
);

-- Aktivera Row Level Security (tillåt allt via service role key)
alter table prompt_sessions enable row level security;

create policy "Allow all via service role"
  on prompt_sessions
  for all
  using (true)
  with check (true);
