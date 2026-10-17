-- Shows whose transcripts live on the publisher's web pages at a date-coded address (e.g. BBC Learning English).
alter table public.shows add column if not exists page_url text;
-- Short Korean introductions shown in small type in the app (written by the worker from the feed descriptions).
alter table public.shows add column if not exists intro_ko text;
alter table public.episodes add column if not exists intro_ko text;
