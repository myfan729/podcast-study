-- When an episode is queued, wake the GitHub worker right away (repository_dispatch "process").
-- Needs a GitHub fine-grained token (this repo, "Contents: Read and write") stored once in Vault:
--   select vault.create_secret('<token>', 'github_dispatch_token');
-- Without it nothing breaks: the worker's schedule picks queued episodes up later.
create extension if not exists pg_net;

create or replace function public.dispatch_worker() returns trigger
language plpgsql security definer set search_path = public as $$
declare tok text;
begin
  begin
    select decrypted_secret into tok from vault.decrypted_secrets where name = 'github_dispatch_token' limit 1;
  exception when others then tok := null;
  end;
  if tok is not null then
    perform net.http_post(
      url := 'https://api.github.com/repos/myfan729/podcast-study/dispatches',
      headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                    'User-Agent', 'podcast-study-db', 'Content-Type', 'application/json'),
      body := jsonb_build_object('event_type', 'process'));
  end if;
  return new;
end $$;

drop trigger if exists episodes_queued on public.episodes;
create trigger episodes_queued after update of status on public.episodes
  for each row when (new.status = 'queued' and old.status is distinct from 'queued')
  execute function public.dispatch_worker();
