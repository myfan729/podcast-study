-- Pre-build new episodes of shows people follow, so opening them is instant.
-- 'prefetch' = queued by the hourly prefetch job (low priority); a user opening it promotes it to 'queued'.
alter table public.episodes drop constraint if exists episodes_status_check;
alter table public.episodes add constraint episodes_status_check
  check (status in ('none', 'prefetch', 'queued', 'processing', 'ready', 'failed', 'no_transcript'));

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
  if e.status in ('none', 'failed', 'prefetch') and e.attempts < 3 then
    update episodes set status = 'queued', requested_at = now(), error = null where id = ep;
    e.status := 'queued';
    perform pg_notify('episode_queued', ep::text);
  end if;
  return jsonb_build_object('status', e.status, 'unlocked', true, 'free_left', left_, 'pro', pro);
end $$;
