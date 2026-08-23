-- Let authorized race-day users prepare a shared checkpoint snapshot without
-- starting the authoritative race clock.
create or replace function public.prepare_race_session(
    p_race_id uuid,
    p_checkpoints jsonb
)
returns setof public.race_sessions
language plpgsql
security definer
set search_path = public
as $$
declare
    v_session public.race_sessions%rowtype;
begin
    perform public.require_app_role(array['coach','admin','timer']);
    perform pg_advisory_xact_lock(hashtextextended(p_race_id::text, 0));

    if p_checkpoints is null or jsonb_typeof(p_checkpoints) <> 'array'
       or jsonb_array_length(p_checkpoints) = 0 then
        raise exception 'checkpoint snapshot is required';
    end if;

    select * into v_session
    from public.race_sessions
    where race_id = p_race_id
      and status in ('ready','running','paused')
    order by created_at desc, id desc
    limit 1
    for update;

    if not found then
        insert into public.race_sessions (race_id, status, started_at, elapsed_offset_seconds)
        values (p_race_id, 'ready', null, 0)
        returning * into v_session;
    end if;

    insert into public.race_session_checkpoints (
        race_session_id, checkpoint_sequence, label, distance_meters,
        distance_unit, lap_number, checkpoint_type, source_checkpoint_id, is_finish
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

revoke all on function public.prepare_race_session(uuid,jsonb) from public, anon;
grant execute on function public.prepare_race_session(uuid,jsonb) to authenticated;
notify pgrst, 'reload schema';
