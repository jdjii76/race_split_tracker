-- Race Split Tracker development Supabase bootstrap/reference snapshot.
--
-- NOT AUTHORITATIVE: the ordered files in supabase/migrations/ are the only
-- production schema history and must be used for upgrades. This convenience
-- snapshot must never be used to infer which migrations an existing database
-- has applied.
--
-- Run this file only in a NEW, SEPARATE DEVELOPMENT Supabase project. It
-- reproduces the schema required by the protected prototype from the canonical
-- migration chain at the time this snapshot was refreshed.
-- Do not run this bootstrap against the existing production project.
--
-- When refreshing this snapshot, apply the complete unique-version chain from
-- supabase/migrations/ to an empty database and regenerate/reference that result.
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
-- Phase 4.3A: safe shared split insertion and lightweight participant attribution.
alter table public.split_events
    add column if not exists recorded_by text;

create unique index if not exists split_events_one_active_checkpoint
    on public.split_events (race_session_id, athlete_id, checkpoint_number)
    where is_deleted = false;

-- Lock the race session while allocating event_order so simultaneous timer clients
-- cannot choose the same sequence. The partial unique index supplies the final
-- concurrency-safe duplicate guard.
create or replace function public.record_shared_split(p_event jsonb)
returns setof public.split_events
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_session_id uuid := (p_event->>'race_session_id')::uuid;
    v_order integer;
begin
    perform 1 from public.race_sessions where id = v_session_id for update;
    if not found then
        raise exception 'Race session not found';
    end if;

    select coalesce(max(event_order), 0) + 1 into v_order
      from public.split_events where race_session_id = v_session_id;

    return query
    insert into public.split_events (
        id, race_session_id, athlete_id, athlete_name, bib_number,
        checkpoint_number, checkpoint_label, elapsed_seconds, recorded_at,
        event_order, is_deleted, recorded_by
    ) values (
        coalesce((p_event->>'id')::uuid, gen_random_uuid()), v_session_id,
        p_event->>'athlete_id', p_event->>'athlete_name', p_event->>'bib_number',
        (p_event->>'checkpoint_number')::integer, p_event->>'checkpoint_label',
        (p_event->>'elapsed_seconds')::numeric,
        coalesce((p_event->>'recorded_at')::timestamptz, timezone('utc', now())),
        v_order, false, nullif(trim(p_event->>'recorded_by'), '')
    ) returning *;
end;
$$;

grant execute on function public.record_shared_split(jsonb) to anon;

-- Source: supabase/migrations/007_fast_validated_split_rpc.sql
-- Validate split identity and progression inside the single authoritative write.
create or replace function public.record_shared_split(p_event jsonb)
returns setof public.split_events
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_session public.race_sessions%rowtype;
    v_athlete public.race_athletes%rowtype;
    v_checkpoint public.race_session_checkpoints%rowtype;
    v_session_id uuid := (p_event->>'race_session_id')::uuid;
    v_completed integer;
    v_order integer;
begin
    select * into v_session from public.race_sessions
      where id = v_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_session.status <> 'running' or v_session.started_at is null then
        raise exception 'Race session is not running';
    end if;

    select * into v_athlete from public.race_athletes
      where race_id = v_session.race_id
        and athlete_id = p_event->>'athlete_id' and active = true;
    if not found then raise exception 'Invalid athlete for this race session'; end if;

    select count(*) into v_completed from public.split_events
      where race_session_id = v_session_id
        and athlete_id = v_athlete.athlete_id and is_deleted = false;
    select * into v_checkpoint from public.race_session_checkpoints
      where race_session_id = v_session_id
      order by checkpoint_sequence offset v_completed limit 1;
    if not found then raise exception 'Athlete has no remaining checkpoint'; end if;
    if (p_event->>'checkpoint_number')::integer <> v_checkpoint.checkpoint_sequence then
        raise exception 'Unexpected checkpoint progression';
    end if;

    select coalesce(max(event_order), 0) + 1 into v_order
      from public.split_events where race_session_id = v_session_id;
    return query insert into public.split_events (
        id, race_session_id, athlete_id, athlete_name, bib_number,
        checkpoint_number, checkpoint_label, elapsed_seconds, recorded_at,
        event_order, is_deleted, recorded_by
    ) values (
        coalesce((p_event->>'id')::uuid, gen_random_uuid()), v_session_id,
        v_athlete.athlete_id, v_athlete.name, v_athlete.bib_number,
        v_checkpoint.checkpoint_sequence, v_checkpoint.label,
        (p_event->>'elapsed_seconds')::numeric,
        coalesce((p_event->>'recorded_at')::timestamptz, timezone('utc', now())),
        v_order, false, nullif(trim(p_event->>'recorded_by'), '')
    ) returning *;
end;
$$;

grant execute on function public.record_shared_split(jsonb) to anon;
-- Application-level single-school branding settings. Image bytes live in Storage.
create table if not exists public.school_profiles (
    id uuid primary key default gen_random_uuid(),
    profile_key text not null unique,
    school_name text not null check (length(trim(school_name)) > 0),
    short_name text not null check (length(trim(short_name)) > 0),
    program_name text, mascot text, city text, state text, app_title text,
    primary_color text not null check (primary_color ~ '^#[0-9A-Fa-f]{6}$'),
    secondary_color text not null check (secondary_color ~ '^#[0-9A-Fa-f]{6}$'),
    accent_color text not null check (accent_color ~ '^#[0-9A-Fa-f]{6}$'),
    text_on_primary text not null check (text_on_primary ~ '^#[0-9A-Fa-f]{6}$'),
    logo_path text, compact_logo_path text,
    header_style text not null default 'standard' check (header_style in ('standard','logo_left','compact','text_only')),
    show_logo_on_dashboard boolean not null default true,
    show_logo_on_timing boolean not null default true,
    include_branding_on_exports boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);
alter table public.school_profiles enable row level security;
-- DEVELOPMENT ONLY: the in-app passcode is a UI gate, not database authorization.
-- Replace with authenticated administrator policies before public deployment.
do $$ begin
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='school_profiles' and policyname='dev_anon_all_school_profiles') then
        create policy dev_anon_all_school_profiles on public.school_profiles for all to anon using (true) with check (true);
    end if;
end $$;

-- Permanent school roster with backward-compatible race roster linkage.
-- Requires 008_school_branding.sql because school_profile_id references its UUID primary key.
-- Existing race-athlete rows remain unlinked; this migration never matches by name.
create table if not exists public.athletes (
    id uuid primary key default gen_random_uuid(),
    school_profile_id uuid null,
    first_name text not null check (length(trim(first_name)) > 0),
    last_name text not null check (length(trim(last_name)) > 0),
    preferred_name text,
    graduation_year integer check (graduation_year is null or graduation_year between 2000 and 2100),
    gender text,
    team_division text,
    status text not null default 'active' check (status in ('active','inactive','injured','graduated')),
    athlete_number text,
    notes text,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    constraint athletes_school_profile_id_fkey foreign key (school_profile_id)
        references public.school_profiles(id) on delete restrict
);
alter table public.athletes add column if not exists school_profile_id uuid null;
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.athletes'::regclass
          and conname = 'athletes_school_profile_id_fkey'
    ) then
        alter table public.athletes
            add constraint athletes_school_profile_id_fkey
            foreign key (school_profile_id) references public.school_profiles(id) on delete restrict;
    end if;
end $$;
create index if not exists idx_athletes_school_profile on public.athletes(school_profile_id);
create index if not exists idx_athletes_status on public.athletes(status);
create index if not exists idx_athletes_graduation_year on public.athletes(graduation_year);
create index if not exists idx_athletes_last_name on public.athletes(lower(last_name));

-- Migration 004 used athlete_id text as a race-local identity. Rename that
-- column only when it is still text, preserving every existing value and row.
do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'race_athletes'
          and column_name = 'athlete_id' and data_type = 'text'
    ) then
        alter table public.race_athletes drop constraint if exists race_athletes_race_athlete_unique;
        alter table public.race_athletes rename column athlete_id to legacy_athlete_id;
    end if;
end $$;

alter table public.race_athletes add column if not exists athlete_id uuid null;
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.race_athletes'::regclass
          and conname = 'race_athletes_athlete_id_fkey'
    ) then
        alter table public.race_athletes
            add constraint race_athletes_athlete_id_fkey
            foreign key (athlete_id) references public.athletes(id) on delete restrict;
    end if;
end $$;
create unique index if not exists race_athletes_race_permanent_unique
    on public.race_athletes(race_id, athlete_id) where athlete_id is not null;
create unique index if not exists race_athletes_race_legacy_unique
    on public.race_athletes(race_id, legacy_athlete_id)
    where athlete_id is null and legacy_athlete_id is not null;
create index if not exists idx_race_athletes_permanent_athlete
    on public.race_athletes(athlete_id);

alter table public.athletes enable row level security;
grant select, insert, update, delete on table public.athletes to anon;
-- DEVELOPMENT ONLY: matches the current publishable/anon-key prototype access.
-- Replace with authenticated administrator/coach policies before production.
do $$
begin
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='athletes' and policyname='dev_anon_all_athletes') then
        create policy dev_anon_all_athletes on public.athletes for all to anon using (true) with check (true);
    end if;
end $$;

-- Preserve shared split validation for both new permanent UUIDs and old text IDs.
create or replace function public.record_shared_split(p_event jsonb)
returns setof public.split_events language plpgsql security invoker set search_path = public as $$
declare
    v_session public.race_sessions%rowtype;
    v_athlete public.race_athletes%rowtype;
    v_checkpoint public.race_session_checkpoints%rowtype;
    v_session_id uuid := (p_event->>'race_session_id')::uuid;
    v_identity text;
    v_completed integer;
    v_order integer;
begin
    select * into v_session from public.race_sessions where id = v_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_session.status <> 'running' or v_session.started_at is null then raise exception 'Race session is not running'; end if;
    select * into v_athlete from public.race_athletes
      where race_id = v_session.race_id and active = true
        and (athlete_id::text = p_event->>'athlete_id' or legacy_athlete_id = p_event->>'athlete_id');
    if not found then raise exception 'Invalid athlete for this race session'; end if;
    v_identity := coalesce(v_athlete.athlete_id::text, v_athlete.legacy_athlete_id);
    select count(*) into v_completed from public.split_events
      where race_session_id = v_session_id and athlete_id = v_identity and is_deleted = false;
    select * into v_checkpoint from public.race_session_checkpoints
      where race_session_id = v_session_id order by checkpoint_sequence offset v_completed limit 1;
    if not found then raise exception 'Athlete has no remaining checkpoint'; end if;
    if (p_event->>'checkpoint_number')::integer <> v_checkpoint.checkpoint_sequence then raise exception 'Unexpected checkpoint progression'; end if;
    select coalesce(max(event_order), 0) + 1 into v_order from public.split_events where race_session_id = v_session_id;
    return query insert into public.split_events (
      id, race_session_id, athlete_id, athlete_name, bib_number, checkpoint_number,
      checkpoint_label, elapsed_seconds, recorded_at, event_order, is_deleted, recorded_by
    ) values (
      coalesce((p_event->>'id')::uuid, gen_random_uuid()), v_session_id, v_identity,
      v_athlete.name, v_athlete.bib_number, v_checkpoint.checkpoint_sequence,
      v_checkpoint.label, (p_event->>'elapsed_seconds')::numeric,
      coalesce((p_event->>'recorded_at')::timestamptz, timezone('utc', now())),
      v_order, false, nullif(trim(p_event->>'recorded_by'), '')
    ) returning *;
end;
$$;
grant execute on function public.record_shared_split(jsonb) to anon;
-- Allow either permanent UUID identity or preserved legacy text identity.
-- Existing rows and split-event history are not updated or deleted.
alter table public.race_athletes
    alter column athlete_id drop not null,
    alter column legacy_athlete_id drop not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.race_athletes'::regclass
          and conname = 'race_athletes_identity_required'
    ) then
        alter table public.race_athletes
            add constraint race_athletes_identity_required
            check (athlete_id is not null or legacy_athlete_id is not null)
            not valid;
    end if;
end $$;

-- Validation reads existing rows without rewriting them and rejects an unsafe
-- deployment if a pre-existing row has neither identity.
alter table public.race_athletes
    validate constraint race_athletes_identity_required;

-- Retain one race membership per identity type.
create unique index if not exists race_athletes_race_permanent_unique
    on public.race_athletes(race_id, athlete_id)
    where athlete_id is not null;
create unique index if not exists race_athletes_race_legacy_unique
    on public.race_athletes(race_id, legacy_athlete_id)
    where athlete_id is null and legacy_athlete_id is not null;

-- Ask PostgREST to observe the altered nullability and constraint immediately.
notify pgrst, 'reload schema';
