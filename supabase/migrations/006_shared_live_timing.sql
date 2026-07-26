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
