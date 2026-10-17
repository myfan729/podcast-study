-- "이어 듣기" on the home screen: when the user last listened to each unlocked episode
alter table public.unlocks add column if not exists played_at timestamptz;
create index if not exists unlocks_recent on public.unlocks (user_id, played_at desc);
