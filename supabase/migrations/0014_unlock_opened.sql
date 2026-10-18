-- When the user first opened the finished study material (null = not yet: the home screen announces it).
alter table public.unlocks add column if not exists opened_at timestamptz;
-- materials made before this change count as seen
update public.unlocks set opened_at = coalesce(played_at, unlocked_at) where opened_at is null;
