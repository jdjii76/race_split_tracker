-- Race Split Tracker race-scoped roster persistence.
-- SECURITY WARNING: The RLS policy below is DEVELOPMENT-ONLY for the prototype
-- using the publishable/anon role. Replace it with authenticated, owner-based
-- policies before public deployment or storing real athlete data.

create table if not exists public.race_athletes (
    id uuid primary key default gen_random_uuid(),
    race_id uuid not null references public.races(id) on delete cascade,
    athlete_id text not null,
    name text not null check (length(trim(name)) > 0),
    bib_number text,
    gender text,
    grade text,
    team text,
    target_finish_time_seconds numeric check (target_finish_time_seconds is null or target_finish_time_seconds >= 0),
    target_pace_seconds_per_mile numeric check (target_pace_seconds_per_mile is null or target_pace_seconds_per_mile >= 0),
    group_category text,
    display_order integer not null default 0,
    active boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    constraint race_athletes_race_order_unique unique (race_id, display_order),
    constraint race_athletes_race_athlete_unique unique (race_id, athlete_id)
);

create index if not exists idx_race_athletes_race_order on public.race_athletes(race_id, display_order);
create unique index if not exists idx_race_athletes_race_bib_unique on public.race_athletes(race_id, bib_number) where bib_number is not null and length(trim(bib_number)) > 0;
create index if not exists idx_race_athletes_race_active on public.race_athletes(race_id, active, display_order);
create index if not exists idx_race_athletes_athlete_id on public.race_athletes(athlete_id);

alter table public.race_athletes enable row level security;

-- DEVELOPMENT-ONLY POLICY: allows anon/publishable-key read/write access.
-- Replace before public deployment or storing real athlete data.
do $$
begin
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'race_athletes' and policyname = 'dev_anon_all_race_athletes') then
        create policy dev_anon_all_race_athletes on public.race_athletes for all to anon using (true) with check (true);
    end if;
end $$;
