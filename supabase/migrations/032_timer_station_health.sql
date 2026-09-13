-- Lightweight heartbeats complement existing station assignments and Pack
-- events; capture counts and latest athletes remain derived from split_events.
create table if not exists public.timer_station_status (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    race_session_id uuid not null references public.race_sessions(id) on delete cascade,
    checkpoint_number integer not null,
    device_id text not null,
    last_seen timestamptz not null default timezone('utc', now()),
    unique (user_id, race_session_id, device_id)
);
create index if not exists idx_timer_station_status_session_seen
    on public.timer_station_status (race_session_id, last_seen desc);
alter table public.timer_station_status enable row level security;
revoke all on public.timer_station_status from public, anon, authenticated;

create or replace function public.heartbeat_timer_station(
    p_session_id uuid, p_checkpoint_number integer, p_device_id text
) returns void language plpgsql security definer set search_path=public as $$
begin
    perform public.require_app_role(array['timer']);
    if not exists (
        select 1 from public.timer_station_assignments
        where user_id=auth.uid() and race_session_id=p_session_id
          and checkpoint_number=p_checkpoint_number and device_id=trim(p_device_id)
    ) then raise exception 'Timer is not assigned to this station'; end if;
    insert into public.timer_station_status (
        user_id,race_session_id,checkpoint_number,device_id,last_seen
    ) values (
        auth.uid(),p_session_id,p_checkpoint_number,trim(p_device_id),timezone('utc',now())
    ) on conflict (user_id,race_session_id,device_id) do update
      set checkpoint_number=excluded.checkpoint_number,last_seen=excluded.last_seen;
end $$;

create or replace function public.list_timer_station_health(p_session_id uuid)
returns table (
    race_session_id uuid, checkpoint_number integer, checkpoint_label text,
    device_id text, timer_user_id uuid, last_seen timestamptz,
    last_capture_at timestamptz, capture_count bigint, latest_athlete_name text
) language plpgsql security definer set search_path=public as $$
begin
    perform public.require_app_role(array['coach','admin']);
    return query
    select st.race_session_id,st.checkpoint_number,cp.label,st.device_id,
           st.user_id,st.last_seen,last_event.received_at,
           coalesce(captures.capture_count,0),coalesce(last_event.athlete_name,'')
    from public.timer_station_status st
    join public.race_session_checkpoints cp
      on cp.race_session_id=st.race_session_id
     and cp.checkpoint_sequence=st.checkpoint_number
    left join lateral (
        select count(*)::bigint capture_count from public.split_events e
        where e.race_session_id=st.race_session_id
          and e.checkpoint_number=st.checkpoint_number
          and e.device_id=st.device_id and e.capture_mode='pack'
          and e.event_type='split_recorded'
    ) captures on true
    left join lateral (
        select e.received_at,e.athlete_name from public.split_events e
        where e.race_session_id=st.race_session_id
          and e.checkpoint_number=st.checkpoint_number
          and e.device_id=st.device_id and e.capture_mode='pack'
          and e.event_type='split_recorded'
        order by e.received_at desc nulls last,e.event_order desc limit 1
    ) last_event on true
    where st.race_session_id=p_session_id
    order by st.checkpoint_number,st.device_id;
end $$;

revoke all on function public.heartbeat_timer_station(uuid,integer,text) from public,anon;
revoke all on function public.list_timer_station_health(uuid) from public,anon;
grant execute on function public.heartbeat_timer_station(uuid,integer,text) to authenticated;
grant execute on function public.list_timer_station_health(uuid) to authenticated;
notify pgrst,'reload schema';
