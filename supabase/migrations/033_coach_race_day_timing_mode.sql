-- Coaches and admins may operate an assigned timing station without changing
-- their persisted app_users role. Existing station and event validation remains
-- in the canonical timing RPCs.
create or replace function public.require_app_role(p_roles text[])
returns void language plpgsql stable security definer set search_path = public, auth
as $$
begin
    if auth.uid() is null or not (
        public.has_app_role(p_roles)
        or ('coach' = any(p_roles) and public.has_app_role(array['timer']))
        or ('timer' = any(p_roles) and public.has_app_role(array['coach','admin']))
    ) then
        raise exception 'not authorized' using errcode='42501';
    end if;
end;
$$;

-- Preserve the established Finish Line lifecycle path and validation while
-- applying the shared timing-operator capability guard.
create or replace function public.complete_race_timing_at_finish(
    p_session_id uuid, p_checkpoint_number integer
)
returns setof public.race_sessions language plpgsql security definer
set search_path = public, auth as $$
declare v_session public.race_sessions%rowtype; v_now timestamptz;
begin
    perform public.require_app_role(array['timer']);
    select * into v_session from public.race_sessions where id=p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if not exists (
        select 1 from public.race_session_checkpoints
        where race_session_id=p_session_id and checkpoint_sequence=p_checkpoint_number
          and is_finish=true
    ) then raise exception 'Only the Finish Line timer can end race timing' using errcode='42501'; end if;
    if v_session.status='awaiting_review' then return next v_session; return; end if;
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

revoke all on function public.complete_race_timing_at_finish(uuid,integer) from public,anon;
grant execute on function public.complete_race_timing_at_finish(uuid,integer) to authenticated;
notify pgrst,'reload schema';
