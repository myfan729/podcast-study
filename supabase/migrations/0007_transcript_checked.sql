-- When the worker last looked for this episode's web transcript (NPR publishes some late, some never).
alter table public.episodes add column if not exists transcript_checked_at timestamptz;
