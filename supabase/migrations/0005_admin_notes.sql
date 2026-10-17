-- Private key/value notes for the owner (read in the Supabase SQL editor). RLS on, no policies: apps can't read it.
create table if not exists public._admin_notes (key text primary key, value text not null, updated_at timestamptz not null default now());
alter table public._admin_notes enable row level security;
