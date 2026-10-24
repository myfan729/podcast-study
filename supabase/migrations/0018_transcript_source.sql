-- Transcripts are no longer stored by us: the phone fetches them from the publisher.
-- Each episode records where its transcript lives; web-page-only transcripts are opened in the app's browser.
alter table public.episodes add column if not exists transcript_url text;
alter table public.episodes add column if not exists transcript_kind text;   -- vtt | srt | json | text | html | web

update public.episodes e set transcript_kind = 'web', transcript_url = e.episode_url
  from public.shows s where s.id = e.show_id and s.path in ('npr', 'web') and e.transcript_kind is null;

-- study material (sync + words/expressions) only for episodes whose transcript the publisher ships in its feed
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
    if e.transcript_kind = 'web' then
      return jsonb_build_object('status', e.status, 'unlocked', false, 'free_left', left_, 'pro', pro, 'reason', 'web_only');
    end if;
    if coalesce(e.duration_sec, 0) > 3600 then
      return jsonb_build_object('status', e.status, 'unlocked', false, 'free_left', left_, 'pro', pro, 'reason', 'too_long');
    end if;
    if not pro and left_ <= 0 then
      return jsonb_build_object('status', e.status, 'unlocked', false, 'free_left', 0, 'pro', false, 'reason', 'quota');
    end if;
    if not e.has_transcript then
      return jsonb_build_object('status', 'no_transcript', 'unlocked', false, 'free_left', left_, 'pro', pro);
    end if;
    insert into unlocks (user_id, episode_id) values (uid, ep);
    if not pro then left_ := left_ - 1; end if;
  end if;
  if e.status in ('none', 'failed', 'prefetch') and e.attempts < 3 and coalesce(e.transcript_kind, '') <> 'web' then
    update episodes set status = 'queued', requested_at = now(), error = null where id = ep;
    e.status := 'queued';
    perform pg_notify('episode_queued', ep::text);
  end if;
  return jsonb_build_object('status', e.status, 'unlocked', true, 'free_left', left_, 'pro', pro);
end $$;
grant execute on function public.request_episode(uuid) to authenticated;

-- web-page shows aren't prefetched any more
update public.episodes set status = 'none' where status = 'prefetch' and transcript_kind = 'web';
