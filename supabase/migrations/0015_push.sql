-- Push notifications: device tokens, per-user switches, and which episodes were already announced.
create table if not exists public.push_tokens (
  token      text primary key,                 -- Expo push token (one per app install)
  user_id    uuid not null references auth.users(id) on delete cascade,
  platform   text,
  updated_at timestamptz not null default now()
);
alter table public.push_tokens enable row level security;
drop policy if exists "own push tokens" on public.push_tokens;
create policy "own push tokens" on public.push_tokens for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create index if not exists push_tokens_user on public.push_tokens (user_id);

alter table public.profiles add column if not exists notify_study boolean not null default true;     -- 학습자료 준비 알림
alter table public.profiles add column if not exists notify_new_eps boolean not null default true;   -- 구독한 쇼 새 에피소드 알림

alter table public.episodes add column if not exists notified_at timestamptz;   -- new-episode push already sent
update public.episodes set notified_at = now() where notified_at is null;       -- don't announce the back catalogue
alter table public.unlocks add column if not exists ready_pushed_at timestamptz; -- study-ready push already sent
update public.unlocks set ready_pushed_at = now() where ready_pushed_at is null;
