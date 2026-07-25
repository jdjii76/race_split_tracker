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
