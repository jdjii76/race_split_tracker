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
