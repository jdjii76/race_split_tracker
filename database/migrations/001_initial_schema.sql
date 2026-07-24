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
