-- Add a least-privilege shared timer role for the standalone race-day workflow.

alter table public.app_users drop constraint if exists app_users_role_check;
alter table public.app_users add constraint app_users_role_check
    check (role in ('timer', 'coach', 'admin'));

-- Existing timing RPCs ask for coach capability. Let timer identities pass that
-- function guard; table RLS below still prevents setup, lifecycle, and reporting writes.
create or replace function public.require_app_role(p_roles text[])
returns void language plpgsql stable security definer set search_path = public, auth
as $$
begin
    if auth.uid() is null or not (
        public.has_app_role(p_roles)
        or ('coach' = any(p_roles) and public.has_app_role(array['timer']))
    ) then
        raise exception 'not authorized' using errcode='42501';
    end if;
end;
$$;

create policy app_timer_meets_read on public.meets for select to authenticated
    using (public.has_app_role(array['timer']));
create policy app_timer_races_read on public.races for select to authenticated
    using (public.has_app_role(array['timer']));
create policy app_timer_rosters_read on public.race_athletes for select to authenticated
    using (public.has_app_role(array['timer']));
create policy app_timer_sessions_read on public.race_sessions for select to authenticated
    using (public.has_app_role(array['timer']));
create policy app_timer_checkpoints_read on public.race_session_checkpoints for select to authenticated
    using (public.has_app_role(array['timer']));
create policy app_timer_events_read on public.split_events for select to authenticated
    using (public.has_app_role(array['timer']));
create policy app_timer_events_insert on public.split_events for insert to authenticated
    with check (public.has_app_role(array['timer']));
create policy app_timer_outcomes_read on public.race_session_athlete_outcomes for select to authenticated
    using (public.has_app_role(array['timer']));

-- This RPC performs the validated, server-clocked insert and locks its session
-- row. SECURITY DEFINER permits that narrow operation without giving timers a
-- general race_sessions UPDATE policy (and therefore lifecycle control).
alter function public.record_shared_split(jsonb) security definer;
