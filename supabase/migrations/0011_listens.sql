-- Plain listening (no study pack, no quota): where each user is in each episode they've played.
create table if not exists public.listens (
  user_id      uuid not null references auth.users(id) on delete cascade,
  episode_id   uuid not null references public.episodes(id) on delete cascade,
  position_sec real not null default 0,
  finished     boolean not null default false,
  played_at    timestamptz not null default now(),
  primary key (user_id, episode_id)
);
alter table public.listens enable row level security;
drop policy if exists "own listens" on public.listens;
create policy "own listens" on public.listens for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create index if not exists listens_recent on public.listens (user_id, played_at desc);
-- carry over progress already kept on unlocks
insert into public.listens (user_id, episode_id, position_sec, finished, played_at)
  select user_id, episode_id, coalesce(position_sec, 0), coalesce(finished, false), played_at
  from public.unlocks where played_at is not null
on conflict do nothing;
