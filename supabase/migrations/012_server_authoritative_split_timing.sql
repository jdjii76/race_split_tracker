-- Make PostgreSQL authoritative for split timestamps, elapsed time, and order.
-- The client supplies only action identity and optional recorder attribution.
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
    v_existing public.split_events%rowtype;
    v_session_id uuid := (p_event->>'race_session_id')::uuid;
    v_event_id uuid := coalesce((p_event->>'id')::uuid, gen_random_uuid());
    v_identity text;
    v_completed integer;
    v_order integer;
    v_recorded_at timestamptz;
    v_elapsed_seconds numeric;
begin
    -- The session-row lock serializes progression and sequence allocation.
    select * into v_session
    from public.race_sessions
    where id = v_session_id
    for update;
    if not found then
        raise exception 'Race session not found';
    end if;
    select * into v_athlete
    from public.race_athletes
    where race_id = v_session.race_id
      and active = true
      and (
          athlete_id::text = p_event->>'athlete_id'
          or legacy_athlete_id = p_event->>'athlete_id'
      )
    limit 1;
    if not found then
        raise exception 'Invalid athlete for this race session';
    end if;
    v_identity := coalesce(v_athlete.athlete_id::text, v_athlete.legacy_athlete_id);

    -- A retry after an ambiguous HTTP response reuses its request UUID and
    -- receives the original committed row instead of advancing a checkpoint.
    select * into v_existing
    from public.split_events
    where id = v_event_id;
    if found then
        if v_existing.race_session_id <> v_session_id
           or v_existing.athlete_id <> v_identity then
            raise exception 'Split request ID belongs to a different action';
        end if;
        return query select * from public.split_events where id = v_event_id;
        return;
    end if;

    if v_session.status <> 'running' or v_session.started_at is null then
        raise exception 'Race session is not running';
    end if;

    select count(*) into v_completed
    from public.split_events
    where race_session_id = v_session_id
      and athlete_id = v_identity
      and is_deleted = false;

    select * into v_checkpoint
    from public.race_session_checkpoints
    where race_session_id = v_session_id
    order by checkpoint_sequence
    offset v_completed
    limit 1;
    if not found then
        raise exception 'Athlete has no remaining checkpoint';
    end if;
    if (p_event->>'checkpoint_number')::integer <> v_checkpoint.checkpoint_sequence then
        raise exception 'Unexpected checkpoint progression';
    end if;

    select coalesce(max(event_order), 0) + 1 into v_order
    from public.split_events
    where race_session_id = v_session_id;

    v_recorded_at := clock_timestamp();
    v_elapsed_seconds := greatest(
        0,
        v_session.elapsed_offset_seconds
        + extract(epoch from (v_recorded_at - v_session.started_at))
    );

    return query
    insert into public.split_events (
        id,
        race_session_id,
        athlete_id,
        athlete_name,
        bib_number,
        checkpoint_number,
        checkpoint_label,
        elapsed_seconds,
        recorded_at,
        event_order,
        is_deleted,
        recorded_by
    )
    values (
        v_event_id,
        v_session_id,
        v_identity,
        v_athlete.name,
        v_athlete.bib_number,
        v_checkpoint.checkpoint_sequence,
        v_checkpoint.label,
        v_elapsed_seconds,
        v_recorded_at,
        v_order,
        false,
        nullif(trim(p_event->>'recorded_by'), '')
    )
    returning *;
end;
$$;

grant execute on function public.record_shared_split(jsonb) to anon;
grant execute on function public.record_shared_split(jsonb) to authenticated;

notify pgrst, 'reload schema';
