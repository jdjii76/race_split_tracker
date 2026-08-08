-- Enforce one ready/running/paused timing session per race and make race start
-- an atomic, database-authoritative operation.

-- Reconcile a database that already contains duplicate nonterminal sessions.
-- Preserve every row and all owned checkpoints/events; retain the most recent
-- running/paused session (then a ready row) because that best preserves an
-- in-progress race and matches the application's prior active lookup.
with ranked_active as (
    select
        id,
        row_number() over (
            partition by race_id
            order by
                case when status in ('running', 'paused') then 0 else 1 end,
                created_at desc,
                id desc
        ) as active_rank
    from public.race_sessions
    where status in ('ready', 'running', 'paused')
)
update public.race_sessions session
set
    status = 'cancelled',
    ended_at = case
        when session.started_at is not null then coalesce(session.ended_at, timezone('utc', now()))
        else null
    end,
    paused_at = null,
    updated_at = timezone('utc', now())
from ranked_active ranked
where session.id = ranked.id
  and ranked.active_rank > 1;

create unique index if not exists race_sessions_one_active_per_race
    on public.race_sessions (race_id)
    where status in ('ready', 'running', 'paused');

create or replace function public.get_or_create_active_race_session(
    p_race_id uuid,
    p_checkpoints jsonb
)
returns setof public.race_sessions
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_session public.race_sessions%rowtype;
    v_started_at timestamptz;
begin
    -- Serialize independent application processes by race, not by a client UUID.
    perform pg_advisory_xact_lock(hashtextextended(p_race_id::text, 0));

    select *
    into v_session
    from public.race_sessions
    where race_id = p_race_id
      and status in ('ready', 'running', 'paused')
    order by created_at desc, id desc
    limit 1
    for update;

    if found and v_session.status in ('running', 'paused') then
        return query select * from public.race_sessions where id = v_session.id;
        return;
    end if;

    if p_checkpoints is null or jsonb_typeof(p_checkpoints) <> 'array'
       or jsonb_array_length(p_checkpoints) = 0 then
        raise exception 'checkpoint snapshot is required';
    end if;

    v_started_at := clock_timestamp();

    if not found then
        insert into public.race_sessions (
            race_id, status, started_at, elapsed_offset_seconds
        )
        values (p_race_id, 'running', v_started_at, 0)
        returning * into v_session;
    else
        update public.race_sessions
        set
            status = 'running',
            started_at = coalesce(started_at, v_started_at),
            paused_at = null,
            updated_at = timezone('utc', now())
        where id = v_session.id
        returning * into v_session;
    end if;

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
        v_session.id,
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

    return query select * from public.race_sessions where id = v_session.id;
end;
$$;

grant execute on function public.get_or_create_active_race_session(uuid, jsonb) to anon;
grant execute on function public.get_or_create_active_race_session(uuid, jsonb) to authenticated;

notify pgrst, 'reload schema';
