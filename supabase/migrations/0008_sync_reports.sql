-- What the phone's auto-sync found (per listen): lets us see why an episode ends up out of sync.
create table if not exists public.sync_reports (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  episode_id uuid not null references public.episodes(id) on delete cascade,
  ok boolean not null,
  anchors jsonb,
  report jsonb,
  error text,
  created_at timestamptz not null default now()
);
alter table public.sync_reports enable row level security;
create policy "own sync reports insert" on public.sync_reports for insert to authenticated with check (user_id = auth.uid());
