-- Sign-up record: who the account is (nickname) and what they agreed to, with versions and times.
-- Paid plans later hang off the same auth user id (entitlements), so purchases follow the account, not the device.
create table if not exists public.profiles (
  user_id          uuid primary key references auth.users(id) on delete cascade,
  nickname         text not null check (char_length(nickname) between 1 and 20),
  terms_version    text not null,
  privacy_version  text not null,
  age14_confirmed  boolean not null check (age14_confirmed),
  agreed_at        timestamptz not null default now(),
  marketing_opt_in boolean not null default false,
  marketing_at     timestamptz,                -- when the marketing choice was last made (consent record)
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
alter table public.profiles enable row level security;
drop policy if exists "own profile read" on public.profiles;
drop policy if exists "own profile write" on public.profiles;
drop policy if exists "own profile update" on public.profiles;
create policy "own profile read" on public.profiles for select to authenticated using (user_id = auth.uid());
create policy "own profile write" on public.profiles for insert to authenticated with check (user_id = auth.uid());
create policy "own profile update" on public.profiles for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
