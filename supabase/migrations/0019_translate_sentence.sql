-- Tap a sentence → its Korean translation (premium: pro, or an episode whose study material you made).
-- Made on demand with a small model and returned, never stored. The API key lives in Vault ('anthropic_api_key'),
-- put there by the app-db workflow from the repository secret.
create extension if not exists http with schema extensions;

create table if not exists public.translate_log (
  user_id uuid not null references auth.users on delete cascade,
  at timestamptz not null default now()
);
create index if not exists translate_log_user_at on public.translate_log (user_id, at);
alter table public.translate_log enable row level security;   -- no policies: only the function below writes it

create or replace function public.translate_sentence(ep uuid, sentence text, context text default null)
returns text language plpgsql security definer set search_path = public, extensions as $$
declare
  uid uuid := auth.uid();
  key text;
  body jsonb;
  resp extensions.http_response;
  out text;
begin
  if uid is null then raise exception 'not signed in'; end if;
  if sentence is null or length(btrim(sentence)) = 0 then return ''; end if;
  if length(sentence) > 1200 then raise exception 'sentence too long'; end if;
  if not (is_pro(uid) or exists (select 1 from unlocks where user_id = uid and episode_id = ep)) then
    raise exception 'premium';
  end if;
  if (select count(*) from translate_log where user_id = uid and at > now() - interval '1 day') >= 300 then
    raise exception 'daily limit';
  end if;
  select decrypted_secret into key from vault.decrypted_secrets where name = 'anthropic_api_key' limit 1;
  if key is null then raise exception 'translation is not set up'; end if;
  insert into translate_log (user_id) values (uid);

  body := jsonb_build_object(
    'model', 'claude-haiku-5-5', 'max_tokens', 400,
    'system', 'You translate one sentence from an English podcast into natural spoken Korean for a Korean learner. '
              'Keep names in their usual Korean form, keep the speaker''s tone, and reply with the Korean translation only.',
    'messages', jsonb_build_array(jsonb_build_object('role', 'user', 'content',
       coalesce('Previous line (context only, do not translate): ' || left(context, 600) || E'\n\n', '') ||
       'Translate: ' || sentence)));
  perform extensions.http_set_curlopt('CURLOPT_TIMEOUT_MS', '20000');
  select * into resp from extensions.http((
    'POST', 'https://api.anthropic.com/v1/messages',
    array[extensions.http_header('x-api-key', key), extensions.http_header('anthropic-version', '2023-06-01')],
    'application/json', body::text)::extensions.http_request);
  if resp.status <> 200 then raise exception 'translation failed (%)', resp.status; end if;
  out := (resp.content::jsonb) -> 'content' -> 0 ->> 'text';
  return btrim(coalesce(out, ''));
end $$;
revoke execute on function public.translate_sentence(uuid, text, text) from public, anon;
grant execute on function public.translate_sentence(uuid, text, text) to authenticated;

-- keep the log small
select cron.schedule('translate-log-trim', '41 4 * * *', $$delete from public.translate_log where at < now() - interval '3 days'$$);
