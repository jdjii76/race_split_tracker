-- Race Split Tracker development Supabase bootstrap.
--
-- Run this file only in a NEW, SEPARATE DEVELOPMENT Supabase project. It
-- reproduces the schema required by the protected prototype by composing the
-- checked-in migrations in their established order: 001, 003, 004, and 005.
-- Do not run this bootstrap against the existing production project.
--
-- Source manifest:
--   supabase/migrations/001_initial_schema.sql
--   supabase/migrations/003_timing_persistence.sql
--   supabase/migrations/004_race_rosters.sql
--   supabase/migrations/005_race_session_checkpoints.sql
-- Keep this manifest and the source-section markers below in migration order
-- when refreshing the bootstrap for a new development project.
--
-- SECURITY WARNING: The policies in this bootstrap intentionally grant the
-- anon/publishable role broad prototype access. They are development-only and
-- must be replaced before public deployment or storage of real athlete data.


-- ============================================================================
-- Source: supabase/migrations/001_initial_schema.sql
-- ============================================================================

-- Race Split Tracker Phase 1 schema.
-- SECURITY WARNING: The RLS policies below are DEVELOPMENT-ONLY policies for a
-- prototype using the publishable/anon role. Replace these with authenticated,
-- owner-based policies before public deployment or storing real athlete data.

create extension if not exists pgcrypto;

create table if not exists public.meets (
    id uuid primary key default gen_random_uuid(),
    name text not null check (length(trim(name)) > 0),
    meet_date date,
    location text,
    season text,
    notes text,
    status text not null default 'draft' check (status in ('draft', 'active', 'upcoming', 'completed', 'archived')),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.races (
    id uuid primary key default gen_random_uuid(),
    meet_id uuid not null references public.meets(id) on delete cascade,
    name text not null check (length(trim(name)) > 0),
    race_category text,
    scheduled_start timestamptz,
    course_type text check (course_type is null or course_type in ('Track', 'Cross Country')),
    distance_meters numeric not null check (distance_meters > 0),
    checkpoint_mode text,
    status text not null default 'draft' check (status in ('draft', 'ready', 'running', 'paused', 'completed', 'archived')),
    display_order integer not null default 0,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.meet_templates (
    id uuid primary key default gen_random_uuid(),
    name text not null check (length(trim(name)) > 0),
    description text,
    season text,
    status text not null default 'active' check (status in ('active', 'archived')),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    constraint meet_templates_name_unique unique (name)
);

create table if not exists public.template_races (
    id uuid primary key default gen_random_uuid(),
    template_id uuid not null references public.meet_templates(id) on delete cascade,
    name text not null check (length(trim(name)) > 0),
    race_category text,
    distance_meters numeric not null check (distance_meters > 0),
    course_type text check (course_type is null or course_type in ('Track', 'Cross Country')),
    checkpoint_mode text,
    display_order integer not null default 0,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_meets_meet_date on public.meets(meet_date);
create index if not exists idx_meets_season on public.meets(season);
create index if not exists idx_races_meet_order on public.races(meet_id, display_order);
create index if not exists idx_template_races_template_order on public.template_races(template_id, display_order);

alter table public.meets enable row level security;
alter table public.races enable row level security;
alter table public.meet_templates enable row level security;
alter table public.template_races enable row level security;

-- DEVELOPMENT-ONLY POLICY: allows anon/publishable-key read/write access.
-- Replace before public deployment or storing real athlete data.
do $$
begin
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'meets' and policyname = 'dev_anon_all_meets') then
        create policy dev_anon_all_meets on public.meets for all to anon using (true) with check (true);
    end if;
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'races' and policyname = 'dev_anon_all_races') then
        create policy dev_anon_all_races on public.races for all to anon using (true) with check (true);
    end if;
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'meet_templates' and policyname = 'dev_anon_all_meet_templates') then
        create policy dev_anon_all_meet_templates on public.meet_templates for all to anon using (true) with check (true);
    end if;
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'template_races' and policyname = 'dev_anon_all_template_races') then
        create policy dev_anon_all_template_races on public.template_races for all to anon using (true) with check (true);
    end if;
end $$;

-- Idempotent default XC meet template seed. Does not create duplicates on rerun.
insert into public.meet_templates (id, name, description, season, status)
values ('00000000-0000-0000-0000-000000000101', 'Default XC Meet', 'Standard four-race cross country meet', 'Cross Country', 'active')
on conflict (name) do nothing;

insert into public.template_races (id, template_id, name, race_category, distance_meters, course_type, checkpoint_mode, display_order)
values
    ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000101', 'Boys JV', 'JV', 5000, 'Cross Country', 'Standard laps', 0),
    ('00000000-0000-0000-0000-000000000202', '00000000-0000-0000-0000-000000000101', 'Girls JV', 'JV', 5000, 'Cross Country', 'Standard laps', 1),
    ('00000000-0000-0000-0000-000000000203', '00000000-0000-0000-0000-000000000101', 'Boys Varsity', 'Varsity', 5000, 'Cross Country', 'Standard laps', 2),
    ('00000000-0000-0000-0000-000000000204', '00000000-0000-0000-0000-000000000101', 'Girls Varsity', 'Varsity', 5000, 'Cross Country', 'Standard laps', 3)
on conflict (id) do nothing;

-- ============================================================================
-- Source: supabase/migrations/003_timing_persistence.sql
-- ============================================================================

-- Race Split Tracker Phase 1 live timing persistence.
-- SECURITY WARNING: The RLS policies below are DEVELOPMENT-ONLY policies for a
-- prototype using the publishable/anon role. Replace these with authenticated,
-- owner-based policies before public deployment or storing real athlete data.

create table if not exists public.race_sessions (
    id uuid primary key default gen_random_uuid(),
    race_id uuid not null references public.races(id) on delete cascade,
    status text not null default 'ready' check (status in ('ready', 'running', 'paused', 'completed', 'cancelled')),
    started_at timestamptz,
    paused_at timestamptz,
    ended_at timestamptz,
    elapsed_offset_seconds numeric not null default 0 check (elapsed_offset_seconds >= 0),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    check (ended_at is null or started_at is not null),
    check (paused_at is null or status = 'paused')
);

create table if not exists public.split_events (
    id uuid primary key default gen_random_uuid(),
    race_session_id uuid not null references public.race_sessions(id) on delete cascade,
    athlete_id text not null,
    athlete_name text,
    bib_number text,
    checkpoint_number integer not null check (checkpoint_number > 0),
    checkpoint_label text,
    elapsed_seconds numeric not null check (elapsed_seconds >= 0),
    recorded_at timestamptz not null default timezone('utc', now()),
    event_order integer not null check (event_order > 0),
    is_deleted boolean not null default false,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    constraint split_events_session_order_unique unique (race_session_id, event_order)
);

create index if not exists idx_race_sessions_race_status on public.race_sessions(race_id, status, created_at);
create index if not exists idx_race_sessions_race_created on public.race_sessions(race_id, created_at);
create index if not exists idx_split_events_session_order on public.split_events(race_session_id, event_order);
create index if not exists idx_split_events_session_active on public.split_events(race_session_id, is_deleted, event_order);
create index if not exists idx_split_events_athlete_checkpoint on public.split_events(athlete_id, checkpoint_number);

alter table public.race_sessions enable row level security;
alter table public.split_events enable row level security;

-- DEVELOPMENT-ONLY POLICY: allows anon/publishable-key read/write access.
-- Replace before public deployment or storing real athlete data.
do $$
begin
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'race_sessions' and policyname = 'dev_anon_all_race_sessions') then
        create policy dev_anon_all_race_sessions on public.race_sessions for all to anon using (true) with check (true);
    end if;
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'split_events' and policyname = 'dev_anon_all_split_events') then
        create policy dev_anon_all_split_events on public.split_events for all to anon using (true) with check (true);
    end if;
end $$;

-- ============================================================================
-- Source: supabase/migrations/004_race_rosters.sql
-- ============================================================================

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

-- ============================================================================
-- Source: supabase/migrations/005_race_session_checkpoints.sql
-- ============================================================================

-- Race Split Tracker Phase 4.1 race-session checkpoint snapshots.
-- SECURITY WARNING: The RLS policy below is DEVELOPMENT-ONLY for the prototype
-- using the publishable/anon role. Replace it with authenticated, owner-based
-- policies before public deployment or storing real athlete data.

create table if not exists public.race_session_checkpoints (
    id uuid primary key default gen_random_uuid(),
    race_session_id uuid not null references public.race_sessions(id) on delete cascade,
    checkpoint_sequence integer not null check (checkpoint_sequence > 0),
    label text not null check (length(trim(label)) > 0),
    distance_meters numeric not null check (distance_meters >= 0),
    distance_unit text not null default 'meters',
    lap_number integer,
    checkpoint_type text not null default 'split' check (checkpoint_type in ('start', 'split', 'lap', 'mile', 'kilometer', 'finish')),
    source_checkpoint_id text,
    is_finish boolean not null default false,
    created_at timestamptz not null default timezone('utc', now()),
    constraint race_session_checkpoints_sequence_unique unique (race_session_id, checkpoint_sequence)
);

create index if not exists idx_race_session_checkpoints_session_order on public.race_session_checkpoints(race_session_id, checkpoint_sequence);

alter table public.race_session_checkpoints enable row level security;

-- DEVELOPMENT-ONLY POLICY: allows anon/publishable-key read/write access.
-- Replace before public deployment or storing real athlete data.
do $$
begin
    if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'race_session_checkpoints' and policyname = 'dev_anon_all_race_session_checkpoints') then
        create policy dev_anon_all_race_session_checkpoints on public.race_session_checkpoints for all to anon using (true) with check (true);
    end if;
end $$;

-- Downgrade, if needed for a local prototype reset:
-- drop table if exists public.race_session_checkpoints;

create or replace function public.create_started_race_session_with_checkpoints(
    p_session_id uuid,
    p_race_id uuid,
    p_started_at timestamptz,
    p_elapsed_offset_seconds numeric,
    p_checkpoints jsonb
)
returns setof public.race_sessions
language plpgsql
as $$
begin
    if p_checkpoints is null or jsonb_array_length(p_checkpoints) = 0 then
        raise exception 'checkpoint snapshot is required';
    end if;

    insert into public.race_sessions (id, race_id, status, started_at, elapsed_offset_seconds)
    values (p_session_id, p_race_id, 'ready', p_started_at, p_elapsed_offset_seconds)
    on conflict (id) do nothing;

    insert into public.race_session_checkpoints (
        race_session_id,
        checkpoint_sequence,
        label,
        distance_meters,
        distance_unit,
        lap_number,
        checkpoint_type,
        source_checkpoint_id,
        is_finish
    )
    select
        p_session_id,
        (item->>'checkpoint_sequence')::integer,
        item->>'label',
        (item->>'distance_meters')::numeric,
        coalesce(item->>'distance_unit', 'meters'),
        nullif(item->>'lap_number', '')::integer,
        coalesce(item->>'checkpoint_type', 'split'),
        nullif(item->>'source_checkpoint_id', ''),
        coalesce((item->>'is_finish')::boolean, false)
    from jsonb_array_elements(p_checkpoints) item
    on conflict (race_session_id, checkpoint_sequence) do nothing;

    update public.race_sessions
    set status = 'running', started_at = p_started_at, elapsed_offset_seconds = p_elapsed_offset_seconds, updated_at = timezone('utc', now())
    where id = p_session_id;

    return query select * from public.race_sessions where id = p_session_id;
end;
$$;

-- Additional downgrade step, if needed for a local prototype reset:
-- drop function if exists public.create_started_race_session_with_checkpoints(uuid, uuid, timestamptz, numeric, jsonb);
