-- GitHub often skips or delays scheduled workflow runs (on 2026-10-18 it skipped a whole afternoon, so the
-- chat's evening post never came). The database fires them on time instead, through repository_dispatch
-- with the same token as dispatch_worker(). The GitHub schedules stay as a backup; runs are idempotent.
create extension if not exists pg_cron;
create extension if not exists pg_net;

create or replace function public.gh_dispatch(ev text) returns void
language plpgsql security definer set search_path = public as $$
declare tok text;
begin
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_dispatch_token' limit 1;
  if tok is null then return; end if;
  perform net.http_post(
    url := 'https://api.github.com/repos/myfan729/podcast-study/dispatches',
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'User-Agent', 'podcast-study-db', 'Content-Type', 'application/json'),
    body := jsonb_build_object('event_type', ev));
end $$;
revoke execute on function public.gh_dispatch(text) from public, anon, authenticated;

-- (re)create the jobs; times are UTC (KST = UTC+9)
do $$
declare j record;
begin
  for j in select jobname from cron.job where jobname like 'gh-%' loop perform cron.unschedule(j.jobname); end loop;
end $$;
-- episodes for the chat: Big Take for the 07:00 KST post, the 18:00 KST post, and every 2 h otherwise
select cron.schedule('gh-update-morning',  '3,23,43 20,21 * * *', $$select public.gh_dispatch('update')$$);
select cron.schedule('gh-update-morning2', '3,23 22 * * *',       $$select public.gh_dispatch('update')$$);
select cron.schedule('gh-update-evening',  '3,23,43 7,8 * * *',   $$select public.gh_dispatch('update')$$);
select cron.schedule('gh-update-evening2', '3 9 * * *',           $$select public.gh_dispatch('update')$$);
select cron.schedule('gh-update-2h',       '17 */2 * * *',        $$select public.gh_dispatch('update')$$);
-- the chat posts themselves
select cron.schedule('gh-daily-morning',   '7,37 20-23 * * *',    $$select public.gh_dispatch('daily')$$);
select cron.schedule('gh-daily-evening',   '7,37 7-9 * * *',      $$select public.gh_dispatch('daily')$$);
-- app: hourly feed refresh, prefetch, new-episode pushes
select cron.schedule('gh-prefetch',        '23 * * * *',          $$select public.gh_dispatch('prefetch')$$);
