-- Store policy: users who can create an account must be able to delete it from inside the app.
-- Deleting the auth user removes their subscriptions, unlocks, saved words and entitlements (on delete cascade);
-- shows they added stay in the catalog without the link to them.
alter table public.shows drop constraint if exists shows_added_by_fkey;
alter table public.shows add constraint shows_added_by_fkey foreign key (added_by) references auth.users(id) on delete set null;

create or replace function public.delete_my_account() returns void
language plpgsql security definer set search_path = public, auth as $$
begin
  if auth.uid() is null then raise exception 'not signed in'; end if;
  delete from auth.users where id = auth.uid();
end $$;
revoke all on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;
