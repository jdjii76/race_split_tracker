-- Serialize persisted race lifecycle transitions and derive all official
-- lifecycle timestamps/elapsed offsets from PostgreSQL state and server time.
create or replace function public.transition_race_session(
    p_session_id uuid,
    p_action text
)
returns setof public.race_sessions
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_session public.race_sessions%rowtype;
    v_action text := lower(trim(p_action));
    v_now timestamptz;
begin
    select * into v_session
    from public.race_sessions
    where id = p_session_id
    for update;

    if not found then
        raise exception 'Race session not found';
    end if;
    if v_action not in ('pause', 'resume', 'complete', 'cancel') then
        raise exception 'Unknown race session action: %', p_action;
    end if;
    if v_session.status = 'running' and v_session.started_at is null then
        raise exception 'Running race session has no start timestamp';
    end if;

    -- Idempotent retries return the original authoritative row without
    -- changing timestamps or accumulating elapsed time a second time.
    if (v_action = 'pause' and v_session.status = 'paused')
       or (v_action = 'resume' and v_session.status = 'running')
       or (v_action = 'complete' and v_session.status = 'completed')
       or (v_action = 'cancel' and v_session.status = 'cancelled') then
        return query select * from public.race_sessions where id = p_session_id;
        return;
    end if;

    if (v_action = 'pause' and v_session.status <> 'running')
       or (v_action = 'resume' and v_session.status <> 'paused')
       or (v_action = 'complete' and v_session.status not in ('running', 'paused'))
       or (v_action = 'cancel' and v_session.status not in ('ready', 'running', 'paused')) then
        raise exception 'Invalid race session transition: % from %', v_action, v_session.status;
    end if;

    v_now := clock_timestamp();

    if v_action = 'pause' then
        update public.race_sessions
        set
            status = 'paused',
            elapsed_offset_seconds = elapsed_offset_seconds + greatest(
                0,
                extract(epoch from (v_now - started_at))
            ),
            paused_at = v_now,
            updated_at = v_now
        where id = p_session_id
        returning * into v_session;
    elsif v_action = 'resume' then
        update public.race_sessions
        set
            status = 'running',
            started_at = v_now,
            paused_at = null,
            updated_at = v_now
        where id = p_session_id
        returning * into v_session;
    elsif v_action = 'complete' then
        update public.race_sessions
        set
            status = 'completed',
            elapsed_offset_seconds = case
                when status = 'running' then elapsed_offset_seconds + greatest(
                    0,
                    extract(epoch from (v_now - started_at))
                )
                else elapsed_offset_seconds
            end,
            ended_at = v_now,
            paused_at = null,
            updated_at = v_now
        where id = p_session_id
        returning * into v_session;
    else
        update public.race_sessions
        set
            status = 'cancelled',
            elapsed_offset_seconds = case
                when status = 'running' then elapsed_offset_seconds + greatest(
                    0,
                    extract(epoch from (v_now - started_at))
                )
                else elapsed_offset_seconds
            end,
            ended_at = case when started_at is null then null else v_now end,
            paused_at = null,
            updated_at = v_now
        where id = p_session_id
        returning * into v_session;
    end if;

    return query select * from public.race_sessions where id = p_session_id;
end;
$$;

grant execute on function public.transition_race_session(uuid, text) to anon;
grant execute on function public.transition_race_session(uuid, text) to authenticated;

notify pgrst, 'reload schema';
