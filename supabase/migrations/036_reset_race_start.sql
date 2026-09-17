-- Protected recovery for an accidentally started official clock. This is a
-- narrow SECURITY DEFINER capability; timers receive no table UPDATE grant.
create table if not exists public.race_lifecycle_audit (
    id uuid primary key default gen_random_uuid(),
    race_session_id uuid not null references public.race_sessions(id) on delete cascade,
    action text not null,
    actor_id uuid not null,
    reason text,
    created_at timestamptz not null default timezone('utc', now())
);
alter table public.race_lifecycle_audit enable row level security;
revoke all on public.race_lifecycle_audit from public, anon, authenticated;

create policy race_lifecycle_audit_coach_read on public.race_lifecycle_audit
for select to authenticated using (public.has_app_role(array['coach','admin']));

create or replace function public.reset_race_start(
    p_session_id uuid,
    p_reason text default 'Accidental early start',
    p_checkpoint_number integer default null,
    p_device_id text default null
)
returns setof public.race_sessions
language plpgsql
security definer
set search_path = public, auth
as $$
declare
    v_session public.race_sessions%rowtype;
    v_manager boolean;
begin
    if auth.uid() is null then
        raise exception 'not authorized' using errcode='42501';
    end if;
    select * into v_session from public.race_sessions
    where id=p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;

    v_manager := public.has_app_role(array['coach','admin']);
    if not v_manager and not (
        public.has_app_role(array['timer'])
        and nullif(trim(p_device_id),'') is not null
        and exists (
            select 1
            from public.timer_station_assignments a
            join public.race_session_checkpoints c
              on c.race_session_id=a.race_session_id
             and c.checkpoint_sequence=a.checkpoint_number
            where a.user_id=auth.uid()
              and a.race_session_id=p_session_id
              and a.device_id=trim(p_device_id)
              and a.checkpoint_number=p_checkpoint_number
              and c.is_finish=true
        )
    ) then
        raise exception 'Only a coach/admin or the assigned Finish Line timer can reset the race clock'
            using errcode='42501';
    end if;
    if v_session.status not in ('running','paused') then
        raise exception 'Race start can only be reset while running or paused';
    end if;

    update public.race_sessions set
        status='ready', started_at=null, paused_at=null, ended_at=null,
        elapsed_offset_seconds=0, updated_at=clock_timestamp()
    where id=p_session_id returning * into v_session;

    insert into public.race_lifecycle_audit
        (race_session_id,action,actor_id,reason)
    values
        (p_session_id,'race_start_reset',auth.uid(),coalesce(nullif(trim(p_reason),''),'Accidental early start'));
    return next v_session;
end;
$$;

revoke all on function public.reset_race_start(uuid,text,integer,text) from public, anon;
grant execute on function public.reset_race_start(uuid,text,integer,text) to authenticated;
notify pgrst, 'reload schema';
