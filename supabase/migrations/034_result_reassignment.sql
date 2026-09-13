-- Append-only, race-session-specific correction of an athlete attribution.
create table if not exists public.result_reassignments (
  id uuid primary key default gen_random_uuid(),
  race_session_id uuid not null references public.race_sessions(id) on delete cascade,
  original_athlete_id text not null,
  destination_athlete_id text not null,
  reason text not null check (length(trim(reason)) > 0),
  source text not null default 'manage_results',
  performed_by uuid not null default auth.uid() references auth.users(id) on delete restrict,
  created_at timestamptz not null default clock_timestamp(),
  check (original_athlete_id <> destination_athlete_id)
);
create index if not exists result_reassignments_session_created
  on public.result_reassignments(race_session_id, created_at, id);

alter table public.result_reassignments enable row level security;
drop policy if exists result_reassignments_staff_read on public.result_reassignments;
create policy result_reassignments_staff_read on public.result_reassignments for select to authenticated
  using (public.has_app_role(array['coach','admin']));
drop policy if exists result_reassignments_staff_insert on public.result_reassignments;
create policy result_reassignments_staff_insert on public.result_reassignments for insert to authenticated
  with check (public.has_app_role(array['coach','admin']) and performed_by=auth.uid());
drop policy if exists result_reassignments_public_final_read on public.result_reassignments;
create policy result_reassignments_public_final_read on public.result_reassignments for select to anon
  using (exists(select 1 from public.race_sessions rs where rs.id=race_session_id and rs.status='completed'));

create or replace function public.reassign_race_result(
  p_id uuid, p_session_id uuid, p_original_athlete_id text,
  p_destination_athlete_id text, p_reason text,
  p_source text default 'manage_results')
returns setof public.result_reassignments
language plpgsql security invoker set search_path=public as $$
declare
  v_session public.race_sessions%rowtype;
  v_athlete public.athletes%rowtype;
begin
  perform public.require_app_role(array['coach','admin']);
  if length(trim(coalesce(p_reason,'')))=0 then raise exception 'A correction reason is required'; end if;
  if p_original_athlete_id=p_destination_athlete_id then raise exception 'Choose a different destination athlete'; end if;
  select * into v_session from public.race_sessions where id=p_session_id for update;
  if not found or v_session.status not in ('awaiting_review','completed') then
    raise exception 'Results can only be reassigned after race timing ends';
  end if;
  select * into v_athlete from public.athletes where id::text=p_destination_athlete_id and status='active';
  if not found then raise exception 'Select an active athlete from the permanent roster'; end if;

  if exists(select 1 from public.split_events e where e.race_session_id=p_session_id
      and e.athlete_id=p_destination_athlete_id and not e.is_deleted
      and e.event_type not in ('split_voided','pack_conflict')
      and not exists(select 1 from public.split_events x where x.target_event_id=e.id and x.event_type='split_voided'))
    or exists(select 1 from public.result_events e where e.race_session_id=p_session_id and e.athlete_id=p_destination_athlete_id)
    or exists(select 1 from public.race_session_athlete_outcomes o where o.race_session_id=p_session_id and o.athlete_id=p_destination_athlete_id)
    or exists(select 1 from public.result_reassignments r where r.race_session_id=p_session_id and r.destination_athlete_id=p_destination_athlete_id) then
    raise exception 'The destination athlete already has timing or result data in this race. Resolve that conflict in Manage Results first';
  end if;
  if not (exists(select 1 from public.split_events e where e.race_session_id=p_session_id
      and e.athlete_id=p_original_athlete_id and not e.is_deleted
      and e.event_type not in ('split_voided','pack_conflict')
      and not exists(select 1 from public.split_events x where x.target_event_id=e.id and x.event_type='split_voided'))
    or exists(select 1 from public.result_events e where e.race_session_id=p_session_id and e.athlete_id=p_original_athlete_id)
    or exists(select 1 from public.race_session_athlete_outcomes o where o.race_session_id=p_session_id and o.athlete_id=p_original_athlete_id)) then
    raise exception 'The source athlete has no performance to reassign';
  end if;

  if not exists(select 1 from public.race_athletes where race_id=v_session.race_id and athlete_id=v_athlete.id) then
    insert into public.race_athletes(race_id, athlete_id, legacy_athlete_id, name, gender, team, display_order, active)
    values(v_session.race_id, v_athlete.id, null, v_athlete.first_name || ' ' || v_athlete.last_name,
           v_athlete.gender, v_athlete.team_division,
           coalesce((select max(display_order)+1 from public.race_athletes where race_id=v_session.race_id),0), true);
  end if;
  return query insert into public.result_reassignments(
      id,race_session_id,original_athlete_id,destination_athlete_id,reason,source,performed_by)
    values(p_id,p_session_id,p_original_athlete_id,p_destination_athlete_id,trim(p_reason),p_source,auth.uid())
    returning *;
end $$;
grant execute on function public.reassign_race_result(uuid,uuid,text,text,text,text) to authenticated;
grant select on public.result_reassignments to anon, authenticated;
grant insert on public.result_reassignments to authenticated;
notify pgrst, 'reload schema';
