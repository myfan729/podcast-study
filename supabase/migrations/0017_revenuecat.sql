-- Paid plan through RevenueCat (Google Play subscriptions). The app buys; the server asks RevenueCat who is
-- entitled to "pro" and writes public.entitlements (the only thing is_pro() reads). No webhook needed:
-- the app calls sync_my_pro() after a purchase/restore and on launch, and a daily job re-checks payers
-- (renewals, cancellations, refunds). Needs the RevenueCat *secret* API key once in Vault:
--   select vault.create_secret('<sk_...>', 'revenuecat_secret');
create extension if not exists http with schema extensions;

create or replace function public.rc_sync(uid uuid) returns boolean
language plpgsql security definer set search_path = public, extensions as $$
declare
  key text; resp extensions.http_response; ent jsonb; exp timestamptz; active boolean;
begin
  if uid is null then return false; end if;
  -- hand-granted plans (owner, store review) are never overwritten
  if exists (select 1 from entitlements where user_id = uid and source in ('owner', 'store-review', 'manual')) then
    return is_pro(uid);
  end if;
  select decrypted_secret into key from vault.decrypted_secrets where name = 'revenuecat_secret' limit 1;
  if key is null then return is_pro(uid); end if;
  select * into resp from extensions.http((
    'GET', 'https://api.revenuecat.com/v1/subscribers/' || uid::text,
    array[extensions.http_header('Authorization', 'Bearer ' || key)], null, null)::extensions.http_request);
  if resp.status <> 200 then return is_pro(uid); end if;
  ent := (resp.content::jsonb) -> 'subscriber' -> 'entitlements' -> 'pro';
  if ent is null or jsonb_typeof(ent) <> 'object' then
    exp := null; active := false;
  else
    exp := nullif(ent ->> 'expires_date', '')::timestamptz;
    active := exp is null or exp > now();
  end if;
  insert into entitlements (user_id, plan, expires_at, source, updated_at)
  values (uid, case when active then 'pro' else 'free' end, exp, 'revenuecat', now())
  on conflict (user_id) do update set plan = excluded.plan, expires_at = excluded.expires_at, source = 'revenuecat', updated_at = now();
  return active;
end $$;
revoke execute on function public.rc_sync(uuid) from public, anon, authenticated;

create or replace function public.sync_my_pro() returns boolean
language sql security definer set search_path = public as $$ select public.rc_sync(auth.uid()) $$;
grant execute on function public.sync_my_pro() to authenticated;

do $$ begin perform cron.unschedule('rc-sync-daily'); exception when others then null; end $$;
select cron.schedule('rc-sync-daily', '17 3 * * *',
  $$select public.rc_sync(user_id) from public.entitlements where source = 'revenuecat'$$);
