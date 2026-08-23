-- Separate the end of live capture from final result publication.

alter table public.race_sessions drop constraint if exists race_sessions_status_check;
alter table public.race_sessions add constraint race_sessions_status_check
    check (status in ('ready','running','paused','awaiting_review','completed','cancelled'));

create or replace function public.complete_race_timing(p_session_id uuid)
returns setof public.race_sessions
language plpgsql security invoker set search_path = public as $$
declare v_session public.race_sessions%rowtype; v_now timestamptz;
begin
    if auth.uid() is null or not public.has_app_role(array['coach','admin']) then
        raise exception 'not authorized' using errcode='42501';
    end if;
    select * into v_session from public.race_sessions where id=p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_session.status='awaiting_review' then
        return query select * from public.race_sessions where id=p_session_id; return;
    end if;
    if v_session.status not in ('running','paused') then
        raise exception 'Race timing can only end from a running or paused session';
    end if;
    v_now:=clock_timestamp();
    update public.race_sessions set
        status='awaiting_review',
        elapsed_offset_seconds=case when status='running' then
            elapsed_offset_seconds+greatest(0,extract(epoch from(v_now-started_at)))
            else elapsed_offset_seconds end,
        ended_at=v_now, paused_at=null, updated_at=v_now
    where id=p_session_id returning * into v_session;
    return next v_session;
end $$;

create or replace function public.finalize_race_session(p_session_id uuid)
returns setof public.race_sessions
language plpgsql security invoker set search_path = public as $$
declare v_session public.race_sessions%rowtype; v_now timestamptz;
begin
    if auth.uid() is null or not public.has_app_role(array['coach','admin']) then
        raise exception 'not authorized' using errcode='42501';
    end if;
    select * into v_session from public.race_sessions where id=p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_session.status='completed' then
        return query select * from public.race_sessions where id=p_session_id; return;
    end if;
    if v_session.status not in ('running','paused','awaiting_review') then
        raise exception 'Race session cannot be finished from its current state';
    end if;
    if exists (
        select 1 from public.race_athletes ra
        where ra.race_id=v_session.race_id and ra.active=true
        and not exists (
            select 1 from public.split_events se
            join public.race_session_checkpoints cp on cp.race_session_id=se.race_session_id
              and cp.checkpoint_sequence=se.checkpoint_number and cp.is_finish=true
            where se.race_session_id=p_session_id and se.is_deleted=false
              and se.athlete_id=coalesce(ra.athlete_id::text,ra.legacy_athlete_id)
              and se.event_type not in ('split_voided','pack_conflict')
              and not exists(select 1 from public.split_events v where v.target_event_id=se.id and v.event_type='split_voided')
        )
        and not exists (
            select 1 from public.race_session_athlete_outcomes o
            where o.race_session_id=p_session_id
              and o.athlete_id=coalesce(ra.athlete_id::text,ra.legacy_athlete_id) and o.status='dnf'
        )
        and not exists (
            select 1 from public.result_events e
            where e.race_session_id=p_session_id
              and e.athlete_id=coalesce(ra.athlete_id::text,ra.legacy_athlete_id)
              and not exists(select 1 from public.result_events n where n.supersedes_id=e.id)
        )
    ) then raise exception 'Resolve every unfinished athlete before finishing the race'; end if;
    v_now:=clock_timestamp();
    update public.race_sessions set
        status='completed',
        elapsed_offset_seconds=case when status='running' then
            elapsed_offset_seconds+greatest(0,extract(epoch from(v_now-started_at)))
            else elapsed_offset_seconds end,
        ended_at=coalesce(ended_at,v_now), paused_at=null, updated_at=v_now
    where id=p_session_id returning * into v_session;
    return next v_session;
end $$;

create or replace function public.append_post_race_result(
 p_id uuid,p_session_id uuid,p_athlete_id text,p_status text,p_finish_seconds numeric,p_source text,
 p_splits jsonb default '{}'::jsonb,p_note text default null,p_supersedes_id uuid default null)
returns setof public.result_events language plpgsql security invoker set search_path=public as $$
declare v_session public.race_sessions%rowtype; v_current uuid; v_value numeric; v_previous numeric := 0;
begin
 if auth.uid() is null or not public.has_app_role(array['coach','admin']) then
   raise exception 'not authorized' using errcode='42501';
 end if;
 select * into v_session from public.race_sessions where id=p_session_id for update;
 if not found or v_session.status not in ('awaiting_review','completed') then
   raise exception 'Results can only be managed after race timing ends';
 end if;
 if not exists(select 1 from public.race_athletes ra where ra.race_id=v_session.race_id and (ra.athlete_id::text=p_athlete_id or ra.legacy_athlete_id=p_athlete_id)) then raise exception 'Athlete does not belong to this race'; end if;
 if p_status not in ('finished','dnf','dns') or p_source not in ('live','manual','official','imported') then raise exception 'Invalid result status or source'; end if;
 if (p_status='finished' and coalesce(p_finish_seconds,0)<=0) or (p_status<>'finished' and p_finish_seconds is not null) then raise exception 'A finished result requires a positive time; DNF/DNS cannot have one'; end if;
 for v_value in select value::text::numeric from jsonb_each(coalesce(p_splits,'{}'::jsonb)) order by key::integer loop
   if v_value<=v_previous or (p_finish_seconds is not null and v_value>p_finish_seconds) then raise exception 'Split times must increase and cannot exceed the finish'; end if;
   v_previous:=v_value;
 end loop;
 select e.id into v_current from public.result_events e where e.race_session_id=p_session_id and e.athlete_id=p_athlete_id
   and not exists(select 1 from public.result_events n where n.supersedes_id=e.id) order by e.created_at desc,e.id desc limit 1;
 if v_current is distinct from p_supersedes_id then raise exception 'This result changed since it was loaded'; end if;
 return query insert into public.result_events(id,race_session_id,athlete_id,status,finish_seconds,source,splits,note,supersedes_id,created_by)
 values(p_id,p_session_id,p_athlete_id,p_status,round(p_finish_seconds,2),p_source,coalesce(p_splits,'{}'::jsonb),nullif(trim(p_note),''),p_supersedes_id,auth.uid()) returning *;
end $$;

revoke all on function public.complete_race_timing(uuid) from public,anon;
grant execute on function public.complete_race_timing(uuid) to authenticated;
notify pgrst,'reload schema';
