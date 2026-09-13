-- Atomic, auditable live-timing correction operations.
-- Existing split rows are retained and projections continue to use is_deleted.

alter table public.split_events add column if not exists correction_type text null;
alter table public.split_events add column if not exists corrected_at timestamptz null;
alter table public.split_events add column if not exists corrected_by text null;

alter table public.split_events drop constraint if exists split_events_correction_type_check;
alter table public.split_events add constraint split_events_correction_type_check
    check (correction_type is null or correction_type in ('invalidated', 'manual'));

create index if not exists idx_split_events_session_correction_activity
    on public.split_events (race_session_id, corrected_at desc)
    where corrected_at is not null;

create or replace function public.invalidate_split_event(
    p_event_id uuid,
    p_session_id uuid,
    p_athlete_id text,
    p_checkpoint_number integer,
    p_corrected_by text default null,
    p_require_latest boolean default false
)
returns setof public.split_events
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_event public.split_events%rowtype;
begin
    perform 1 from public.race_sessions where id = p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;

    select * into v_event from public.split_events
    where id = p_event_id for update;
    if not found then raise exception 'Split event not found'; end if;
    if v_event.race_session_id <> p_session_id
       or v_event.athlete_id <> p_athlete_id
       or v_event.checkpoint_number <> p_checkpoint_number then
        raise exception 'Split correction no longer matches the selected race-session event';
    end if;
    if v_event.is_deleted then
        raise exception 'Split event was already corrected by another user';
    end if;
    if p_require_latest and exists (
        select 1 from public.split_events
        where race_session_id = p_session_id and is_deleted = false
          and event_order > v_event.event_order
    ) then
        raise exception 'A newer split was recorded; refresh before choosing Undo Last Split';
    end if;

    return query update public.split_events
    set is_deleted = true,
        correction_type = 'invalidated',
        corrected_at = clock_timestamp(),
        corrected_by = nullif(trim(p_corrected_by), ''),
        updated_at = clock_timestamp()
    where id = p_event_id
    returning *;
end;
$$;

create or replace function public.record_manual_split(p_event jsonb)
returns setof public.split_events
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_session public.race_sessions%rowtype;
    v_athlete public.race_athletes%rowtype;
    v_checkpoint public.race_session_checkpoints%rowtype;
    v_candidate public.race_session_checkpoints%rowtype;
    v_existing public.split_events%rowtype;
    v_session_id uuid := (p_event->>'race_session_id')::uuid;
    v_event_id uuid := coalesce((p_event->>'id')::uuid, gen_random_uuid());
    v_identity text;
    v_checkpoint_number integer := (p_event->>'checkpoint_number')::integer;
    v_elapsed numeric := (p_event->>'elapsed_seconds')::numeric;
    v_previous numeric;
    v_later numeric;
    v_current_elapsed numeric;
    v_order integer;
begin
    select * into v_session from public.race_sessions
    where id = v_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_session.status not in ('running', 'paused') then
        raise exception 'Missed splits can only be added to a running or paused race';
    end if;

    select * into v_athlete from public.race_athletes
    where race_id = v_session.race_id and active = true
      and (athlete_id::text = p_event->>'athlete_id' or legacy_athlete_id = p_event->>'athlete_id')
    limit 1;
    if not found then raise exception 'Invalid athlete for this race session'; end if;
    v_identity := coalesce(v_athlete.athlete_id::text, v_athlete.legacy_athlete_id);

    select * into v_existing from public.split_events where id = v_event_id;
    if found then
        if v_existing.race_session_id <> v_session_id
           or v_existing.athlete_id <> v_identity
           or v_existing.checkpoint_number <> v_checkpoint_number then
            raise exception 'Split request ID belongs to a different action';
        end if;
        return query select * from public.split_events where id = v_event_id;
        return;
    end if;

    -- The only permitted insertion is the first checkpoint absent from the
    -- athlete's active history. This also permits replacing an invalidated
    -- older split while retaining later rows for deterministic replay.
    for v_candidate in
        select * from public.race_session_checkpoints
        where race_session_id = v_session_id order by checkpoint_sequence
    loop
        if not exists (
            select 1 from public.split_events
            where race_session_id = v_session_id and athlete_id = v_identity
              and checkpoint_number = v_candidate.checkpoint_sequence and is_deleted = false
        ) then
            v_checkpoint := v_candidate;
            exit;
        end if;
    end loop;
    if v_checkpoint.id is null or v_checkpoint.checkpoint_sequence <> v_checkpoint_number then
        raise exception 'Manual split must be the athlete''s next missing checkpoint';
    end if;

    select max(elapsed_seconds) into v_previous from public.split_events
    where race_session_id = v_session_id and athlete_id = v_identity and is_deleted = false
      and checkpoint_number < v_checkpoint_number;
    select min(elapsed_seconds) into v_later from public.split_events
    where race_session_id = v_session_id and athlete_id = v_identity and is_deleted = false
      and checkpoint_number > v_checkpoint_number;
    if v_elapsed < 0 or (v_previous is not null and v_elapsed <= v_previous)
       or (v_later is not null and v_elapsed >= v_later) then
        raise exception 'Manual elapsed time must fall between the athlete''s surrounding splits';
    end if;

    v_current_elapsed := v_session.elapsed_offset_seconds;
    if v_session.status = 'running' and v_session.started_at is not null then
        v_current_elapsed := v_current_elapsed + extract(epoch from (clock_timestamp() - v_session.started_at));
    end if;
    if v_elapsed > greatest(0, v_current_elapsed) then
        raise exception 'Manual elapsed time cannot be later than the authoritative race clock';
    end if;

    select coalesce(max(event_order), 0) + 1 into v_order
    from public.split_events where race_session_id = v_session_id;

    return query insert into public.split_events (
        id, race_session_id, athlete_id, athlete_name, bib_number,
        checkpoint_number, checkpoint_label, elapsed_seconds, recorded_at,
        event_order, is_deleted, recorded_by, correction_type, corrected_at, corrected_by
    ) values (
        v_event_id, v_session_id, v_identity, v_athlete.name, v_athlete.bib_number,
        v_checkpoint.checkpoint_sequence, v_checkpoint.label, v_elapsed, clock_timestamp(),
        v_order, false, nullif(trim(p_event->>'recorded_by'), ''), 'manual', clock_timestamp(),
        nullif(trim(p_event->>'recorded_by'), '')
    ) returning *;
end;
$$;

grant execute on function public.invalidate_split_event(uuid, uuid, text, integer, text, boolean) to anon, authenticated;
grant execute on function public.record_manual_split(jsonb) to anon, authenticated;
notify pgrst, 'reload schema';
