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
