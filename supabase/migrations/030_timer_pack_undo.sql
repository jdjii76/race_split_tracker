-- Bind each timer device to one station and allow append-only undo only for
-- that device's Pack Mode captures at that station.
create table if not exists public.timer_station_assignments (
    user_id uuid not null,
    race_session_id uuid not null references public.race_sessions(id) on delete cascade,
    device_id text not null,
    checkpoint_number integer not null,
    assigned_at timestamptz not null default timezone('utc', now()),
    primary key (user_id, race_session_id, device_id)
);
alter table public.timer_station_assignments enable row level security;
revoke all on public.timer_station_assignments from public, anon, authenticated;

create or replace function public.assign_timer_station(
    p_session_id uuid,
    p_checkpoint_number integer,
    p_device_id text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
    perform public.require_app_role(array['timer']);
    if auth.uid() is null or nullif(trim(p_device_id), '') is null then
        raise exception 'Authenticated timer device is required';
    end if;
    if not exists (
        select 1 from public.race_sessions s
        join public.race_session_checkpoints c on c.race_session_id=s.id
        where s.id=p_session_id and s.status in ('ready','running','paused')
          and c.checkpoint_sequence=p_checkpoint_number
    ) then
        raise exception 'Race session checkpoint is not available';
    end if;
    insert into public.timer_station_assignments (
        user_id, race_session_id, device_id, checkpoint_number, assigned_at
    ) values (
        auth.uid(), p_session_id, trim(p_device_id), p_checkpoint_number, timezone('utc', now())
    )
    on conflict (user_id, race_session_id, device_id) do update
    set checkpoint_number=excluded.checkpoint_number, assigned_at=excluded.assigned_at;
end;
$$;

create or replace function public.invalidate_timer_pack_event(
    p_event_id uuid,
    p_session_id uuid,
    p_checkpoint_number integer,
    p_device_id text,
    p_corrected_by text default null
)
returns setof public.split_events
language plpgsql
security definer
set search_path = public
as $$
declare
    v_event public.split_events%rowtype;
    v_order integer;
begin
    perform public.require_app_role(array['timer']);
    perform 1 from public.race_sessions
    where id=p_session_id and status in ('running','paused','awaiting_review')
    for update;
    if not found then
        raise exception 'Race session is finalized or unavailable for timer undo';
    end if;
    if not exists (
        select 1 from public.timer_station_assignments
        where user_id=auth.uid() and race_session_id=p_session_id
          and device_id=trim(p_device_id) and checkpoint_number=p_checkpoint_number
    ) then
        raise exception 'Timer is not assigned to this checkpoint';
    end if;
    select * into v_event from public.split_events
    where id=p_event_id and race_session_id=p_session_id
      and checkpoint_number=p_checkpoint_number
      and capture_mode='pack' and device_id=trim(p_device_id)
    for update;
    if not found then
        raise exception 'Timer can undo only its own station Pack Mode event';
    end if;
    if v_event.is_deleted or v_event.event_type in ('split_voided','pack_conflict')
       or exists (
           select 1 from public.split_events
           where target_event_id=v_event.id and event_type='split_voided'
       ) then
        raise exception 'This timing event was already corrected';
    end if;
    select coalesce(max(event_order),0)+1 into v_order
    from public.split_events where race_session_id=p_session_id;
    return query insert into public.split_events (
        race_session_id, athlete_id, athlete_name, bib_number,
        checkpoint_number, checkpoint_label, elapsed_seconds, recorded_at,
        event_order, recorded_by, correction_type, corrected_at,
        corrected_by, event_type, target_event_id, reason
    ) values (
        p_session_id, v_event.athlete_id, v_event.athlete_name, v_event.bib_number,
        v_event.checkpoint_number, v_event.checkpoint_label, v_event.elapsed_seconds,
        clock_timestamp(), v_order, nullif(trim(p_corrected_by),''), 'invalidated',
        clock_timestamp(), nullif(trim(p_corrected_by),''), 'split_voided',
        v_event.id, 'timer pack undo'
    ) returning *;
end;
$$;

revoke all on function public.assign_timer_station(uuid,integer,text) from public, anon;
revoke all on function public.invalidate_timer_pack_event(uuid,uuid,integer,text,text) from public, anon;
grant execute on function public.assign_timer_station(uuid,integer,text) to authenticated;
grant execute on function public.invalidate_timer_pack_event(uuid,uuid,integer,text,text) to authenticated;
notify pgrst, 'reload schema';
