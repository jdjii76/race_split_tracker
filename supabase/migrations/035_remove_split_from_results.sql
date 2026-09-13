-- Reasoned, append-only post-race checkpoint invalidation.
alter table public.split_events drop constraint if exists split_events_correction_type_check;
alter table public.split_events add constraint split_events_correction_type_check
  check (correction_type is null or correction_type in ('invalidated','manual','removed_from_results'));

create or replace function public.remove_split_from_results(
  p_event_id uuid,
  p_session_id uuid,
  p_checkpoint_number integer,
  p_reason text,
  p_corrected_by text default null
)
returns setof public.split_events
language plpgsql
security invoker
set search_path=public
as $$
declare
  v_event public.split_events%rowtype;
  v_session public.race_sessions%rowtype;
  v_order integer;
  v_actor text;
begin
  perform public.require_app_role(array['coach','admin']);
  if length(trim(coalesce(p_reason,'')))=0 then
    raise exception 'A correction reason is required';
  end if;

  select * into v_session from public.race_sessions where id=p_session_id for update;
  if not found or v_session.status not in ('awaiting_review','completed') then
    raise exception 'Splits can only be removed after race timing ends';
  end if;

  select * into v_event from public.split_events
    where id=p_event_id and race_session_id=p_session_id
      and checkpoint_number=p_checkpoint_number for update;
  if not found then
    raise exception 'Split correction no longer matches the selected race-session event';
  end if;
  if lower(trim(coalesce(v_event.checkpoint_label,'')))='finish'
     or exists(select 1 from public.race_session_checkpoints c
               where c.race_session_id=p_session_id
                 and c.checkpoint_sequence=p_checkpoint_number and c.is_finish) then
    raise exception 'Finish results must be corrected through Manage Results';
  end if;
  if v_event.is_deleted or v_event.event_type in ('split_voided','pack_conflict')
     or exists(select 1 from public.split_events x
               where x.target_event_id=v_event.id and x.event_type='split_voided') then
    raise exception 'The selected split is no longer active. Refresh results and try again';
  end if;

  select coalesce(max(event_order),0)+1 into v_order
    from public.split_events where race_session_id=p_session_id;
  v_actor := coalesce(auth.uid()::text, nullif(trim(p_corrected_by),''));
  return query insert into public.split_events(
    race_session_id,athlete_id,athlete_name,bib_number,checkpoint_number,
    checkpoint_label,elapsed_seconds,recorded_at,event_order,recorded_by,
    correction_type,corrected_at,corrected_by,event_type,target_event_id,reason)
  values(
    p_session_id,v_event.athlete_id,v_event.athlete_name,v_event.bib_number,
    v_event.checkpoint_number,v_event.checkpoint_label,v_event.elapsed_seconds,
    clock_timestamp(),v_order,v_actor,'removed_from_results',clock_timestamp(),v_actor,
    'split_voided',v_event.id,trim(p_reason))
  returning *;
end $$;

grant execute on function public.remove_split_from_results(uuid,uuid,integer,text,text) to authenticated;
notify pgrst,'reload schema';
