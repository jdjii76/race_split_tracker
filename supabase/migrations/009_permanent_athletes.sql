-- Permanent school roster with backward-compatible race roster linkage.
create table if not exists public.athletes (
    id uuid primary key default gen_random_uuid(),
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
    updated_at timestamptz not null default timezone('utc', now())
);
create index if not exists idx_athletes_status on public.athletes(status);
create index if not exists idx_athletes_graduation_year on public.athletes(graduation_year);
create index if not exists idx_athletes_last_name on public.athletes(lower(last_name));

-- Phase 4 used a text athlete_id as the race-local identity. Preserve it rather
-- than guessing at name matches, then add the nullable permanent UUID reference.
do $$ begin
    if exists (select 1 from information_schema.columns where table_schema='public' and table_name='race_athletes' and column_name='athlete_id' and data_type='text') then
        alter table public.race_athletes drop constraint if exists race_athletes_race_athlete_unique;
        alter table public.race_athletes rename column athlete_id to legacy_athlete_id;
    end if;
end $$;
alter table public.race_athletes add column if not exists athlete_id uuid null references public.athletes(id) on delete restrict;
create unique index if not exists race_athletes_race_permanent_unique on public.race_athletes(race_id, athlete_id) where athlete_id is not null;
create unique index if not exists race_athletes_race_legacy_unique on public.race_athletes(race_id, legacy_athlete_id) where athlete_id is null and legacy_athlete_id is not null;
create index if not exists idx_race_athletes_permanent_athlete on public.race_athletes(athlete_id);

alter table public.athletes enable row level security;
-- DEVELOPMENT ONLY, consistent with the prototype's current anon policies.
do $$ begin
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='athletes' and policyname='dev_anon_all_athletes') then
        create policy dev_anon_all_athletes on public.athletes for all to anon using (true) with check (true);
    end if;
end $$;

-- Keep authoritative split validation compatible with permanent and legacy roster rows.
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
