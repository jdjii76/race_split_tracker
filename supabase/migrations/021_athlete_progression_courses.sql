-- Permanent course identity and indexes supporting derived athlete progression.
-- Additive only: existing races retain a NULL course and continue to work.
create table if not exists public.courses (
    id uuid primary key default gen_random_uuid(),
    course_name text not null check (length(trim(course_name)) > 0),
    location text,
    distance_meters double precision check (distance_meters is null or distance_meters > 0),
    notes text,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);
alter table public.races add column if not exists course_id uuid null;
do $$ begin
 if not exists (select 1 from pg_constraint where conrelid='public.races'::regclass and conname='races_course_id_fkey') then
  alter table public.races add constraint races_course_id_fkey foreign key(course_id) references public.courses(id) on delete set null;
 end if;
end $$;
create index if not exists idx_races_course_id on public.races(course_id);
create index if not exists idx_meets_progression_date on public.meets(meet_date, id);
create index if not exists idx_race_sessions_completed_race on public.race_sessions(race_id, created_at) where status='completed';
create index if not exists idx_split_events_history on public.split_events(race_session_id, athlete_id, checkpoint_number, event_order);
alter table public.courses enable row level security;
drop policy if exists app_coach_courses on public.courses;
create policy app_coach_courses on public.courses for all to authenticated
 using (public.has_app_role(array['admin','coach'])) with check (public.has_app_role(array['admin','coach']));
grant select, insert, update, delete on public.courses to authenticated;
revoke all on public.courses from anon;
