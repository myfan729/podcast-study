-- shows whose transcripts come from the publisher's web page (BBC Learning English, SBS)
alter table public.shows drop constraint if exists shows_path_check;
alter table public.shows add constraint shows_path_check check (path in ('rss', 'npr', 'web'));
