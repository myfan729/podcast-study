-- translate_sentence: join all text blocks; fail loudly instead of returning ''
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
  select string_agg(b ->> 'text', '') into out
    from jsonb_array_elements((resp.content::jsonb) -> 'content') b where b ->> 'type' = 'text';
  if coalesce(btrim(out), '') = '' then
    raise exception 'empty translation: %', left(resp.content, 300);
  end if;
  return btrim(out);
end $$;
