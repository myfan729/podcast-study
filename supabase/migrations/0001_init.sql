-- Podcast Study app — initial schema (Supabase / Postgres)
-- Users sign in with Supabase Auth. Episode study packs are built on demand by the worker
-- (GitHub Actions running pipeline/) and stored in the private bucket "episodes";
-- a user can read a pack only after unlocking that episode (quota checked in request_episode()).

create extension if not exists pgcrypto;

-- ---------- catalog ----------
create table public.shows (
  id            uuid primary key default gen_random_uuid(),
  feed_url      text not null unique,
  title         text not null,
  author        text,
  image_url     text,
  description   text,
  language      text default 'en',
  path          text not null check (path in ('rss', 'npr')),     -- how transcripts are obtained
  parser        text,                                            -- web parser for path=npr
  speaker_labels text default 'auto',
  max_minutes   int default 60,
  title_include text,
  title_exclude text,
  catalog       boolean not null default false,                  -- curated / verified list
  category      text,
  level         text,                                            -- rough difficulty band shown in the catalog
  added_by      uuid references auth.users(id),
  refreshed_at  timestamptz,
  created_at    timestamptz not null default now()
);

create table public.episodes (
  id            uuid primary key default gen_random_uuid(),
  show_id       uuid not null references public.shows(id) on delete cascade,
  guid          text not null,
  title         text not null,
  published_at  timestamptz not null,
  duration_sec  int,
  audio_url     text,
  episode_url   text,
  image_url     text,
  description   text,
  has_transcript boolean not null default false,
  status        text not null default 'none'
                check (status in ('none', 'queued', 'processing', 'ready', 'failed', 'no_transcript')),
  error         text,
  attempts      int not null default 0,
  pack_path     text,                                            -- storage: episodes/<id>.json
  sync_path     text,                                            -- storage: episodes/<id>.sync.json
  one_liner_ko  text,
  requested_at  timestamptz,
  ready_at      timestamptz,
  unique (show_id, guid)
);
create index episodes_show_pub on public.episodes (show_id, published_at desc);
create index episodes_queue on public.episodes (status, requested_at) where status in ('queued', 'processing');

-- ---------- per user ----------
create table public.subscriptions (                              -- "following" a show
  user_id   uuid not null references auth.users(id) on delete cascade,
  show_id   uuid not null references public.shows(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, show_id)
);

create table public.unlocks (                                    -- episodes a user opened (quota + access)
  user_id     uuid not null references auth.users(id) on delete cascade,
  episode_id  uuid not null references public.episodes(id) on delete cascade,
  unlocked_at timestamptz not null default now(),
  position_sec real default 0,
  finished    boolean default false,
  primary key (user_id, episode_id)
);

create table public.vocab (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  episode_id  uuid references public.episodes(id) on delete set null,
  kind        text not null check (kind in ('word', 'expression', 'sentence')),
  text        text not null,
  meaning_ko  text,
  note        text,
  example     text,
  cue_start   real,                                              -- where it was heard (seconds, content time)
  created_at  timestamptz not null default now(),
  -- spaced repetition (SM-2 style)
  due_at      timestamptz not null default now(),
  interval_days real not null default 0,
  ease        real not null default 2.5,
  reps        int not null default 0,
  unique (user_id, kind, text)
);

create table public.entitlements (                               -- written by the RevenueCat webhook
  user_id    uuid primary key references auth.users(id) on delete cascade,
  plan       text not null default 'free' check (plan in ('free', 'pro')),
  expires_at timestamptz,
  source     text,
  updated_at timestamptz not null default now()
);

-- ---------- row level security ----------
alter table public.shows enable row level security;
alter table public.episodes enable row level security;
alter table public.subscriptions enable row level security;
alter table public.unlocks enable row level security;
alter table public.vocab enable row level security;
alter table public.entitlements enable row level security;

create policy "catalog readable" on public.shows for select to authenticated using (true);
create policy "episodes readable" on public.episodes for select to authenticated using (true);
create policy "own subscriptions" on public.subscriptions for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "own unlocks read" on public.unlocks for select to authenticated using (user_id = auth.uid());
create policy "own unlocks progress" on public.unlocks for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "own vocab" on public.vocab for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "own plan" on public.entitlements for select to authenticated using (user_id = auth.uid());

-- ---------- quota + request ----------
create or replace function public.is_pro(uid uuid) returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from entitlements e where e.user_id = uid and e.plan = 'pro' and (e.expires_at is null or e.expires_at > now()));
$$;

create or replace function public.free_left(uid uuid) returns int language sql stable security definer set search_path = public as $$
  select greatest(0, 2 - (select count(*) from unlocks u where u.user_id = uid and u.unlocked_at > now() - interval '7 days'))::int;
$$;

-- Called by the app when a user opens an episode. Unlocks it (if the quota allows) and queues processing.
-- Returns {status, unlocked, free_left, pro}.
create or replace function public.request_episode(ep uuid) returns jsonb language plpgsql security definer set search_path = public as $$
declare
  uid uuid := auth.uid();
  e episodes%rowtype;
  already boolean;
  pro boolean;
  left_ int;
begin
  if uid is null then raise exception 'not signed in'; end if;
  select * into e from episodes where id = ep for update;
  if not found then raise exception 'no such episode'; end if;
  select exists (select 1 from unlocks where user_id = uid and episode_id = ep) into already;
  pro := is_pro(uid);
  left_ := free_left(uid);
  if not already then
    if not pro and left_ <= 0 then
      return jsonb_build_object('status', e.status, 'unlocked', false, 'free_left', 0, 'pro', false, 'reason', 'quota');
    end if;
    if not e.has_transcript then
      return jsonb_build_object('status', 'no_transcript', 'unlocked', false, 'free_left', left_, 'pro', pro);
    end if;
    insert into unlocks (user_id, episode_id) values (uid, ep);
    if not pro then left_ := left_ - 1; end if;
  end if;
  if e.status in ('none', 'failed') and e.attempts < 3 then
    update episodes set status = 'queued', requested_at = now(), error = null where id = ep;
    e.status := 'queued';
    perform pg_notify('episode_queued', ep::text);
  end if;
  return jsonb_build_object('status', e.status, 'unlocked', true, 'free_left', left_, 'pro', pro);
end $$;
grant execute on function public.request_episode(uuid) to authenticated;
grant execute on function public.free_left(uuid) to authenticated;
grant execute on function public.is_pro(uuid) to authenticated;

-- ---------- storage: private bucket, readable for unlocked episodes only ----------
insert into storage.buckets (id, name, public) values ('episodes', 'episodes', false) on conflict do nothing;
create policy "read unlocked packs" on storage.objects for select to authenticated using (
  bucket_id = 'episodes'
  and exists (select 1 from public.unlocks u
              where u.user_id = auth.uid()
                and u.episode_id::text = split_part(storage.filename(name), '.', 1))
);
