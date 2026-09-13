-- Durable, idempotent client-captured pack timing metadata and batch ingestion.
alter table public.split_events add column if not exists client_event_id uuid;
alter table public.split_events add column if not exists captured_at timestamptz;
alter table public.split_events add column if not exists received_at timestamptz;
alter table public.split_events add column if not exists capture_mode text not null default 'normal' check(capture_mode in ('normal','pack'));
alter table public.split_events add column if not exists device_id text;
alter table public.split_events add column if not exists capture_sequence bigint;
alter table public.split_events add column if not exists clock_offset_ms numeric;
alter table public.split_events drop constraint if exists split_events_event_type_check;
alter table public.split_events add constraint split_events_event_type_check check(event_type in ('split_recorded','split_voided','split_corrected','split_manual','pack_conflict'));
create unique index if not exists idx_split_events_client_event_id on public.split_events(client_event_id) where client_event_id is not null;
create index if not exists idx_split_events_pack_order on public.split_events(race_session_id,captured_at,capture_sequence) where capture_mode='pack';

create or replace function public.record_pack_split_events(p_session_id uuid,p_events jsonb,p_recorded_by text default null)
returns setof public.split_events language plpgsql security invoker set search_path=public as $$
declare s public.race_sessions%rowtype; x jsonb; a public.race_athletes%rowtype; c public.race_session_checkpoints%rowtype; old public.split_events%rowtype; n integer; conflict boolean; captured timestamptz;
begin
 perform public.require_app_role(array['coach','admin']);
 select * into s from public.race_sessions where id=p_session_id for update;
 if not found or s.status<>'running' or s.started_at is null then raise exception 'Race session is not running'; end if;
 for x in select value from jsonb_array_elements(p_events) order by (value->>'captured_at')::timestamptz,(value->>'capture_sequence')::bigint loop
  select * into old from public.split_events where client_event_id=(x->>'client_event_id')::uuid;
  if found then
   if old.race_session_id<>p_session_id or old.athlete_id<>x->>'athlete_id' then raise exception 'Pack event ID belongs to a different action'; end if;
   return next old; continue;
  end if;
  if (x->>'race_session_id')::uuid<>p_session_id then raise exception 'Pack event session mismatch'; end if;
  select ra.* into a from public.race_athletes ra where ra.race_id=s.race_id and ra.active and (ra.athlete_id::text=x->>'athlete_id' or ra.legacy_athlete_id=x->>'athlete_id') limit 1;
  if not found then raise exception 'Invalid athlete for this race session'; end if;
  select * into c from public.race_session_checkpoints where race_session_id=p_session_id and checkpoint_sequence=(x->>'checkpoint_number')::integer;
  if not found then raise exception 'Invalid checkpoint for this race session'; end if;
  captured=(x->>'captured_at')::timestamptz; if captured<s.started_at then raise exception 'Capture predates race start'; end if;
  select exists(select 1 from public.split_events e where e.race_session_id=p_session_id and e.athlete_id=coalesce(a.athlete_id::text,a.legacy_athlete_id) and e.checkpoint_number=c.checkpoint_sequence and e.event_type not in ('split_voided','pack_conflict') and not e.is_deleted and not exists(select 1 from public.split_events v where v.target_event_id=e.id and v.event_type='split_voided')) into conflict;
  select coalesce(max(event_order),0)+1 into n from public.split_events where race_session_id=p_session_id;
  return query insert into public.split_events(id,client_event_id,race_session_id,athlete_id,athlete_name,bib_number,checkpoint_number,checkpoint_label,elapsed_seconds,recorded_at,event_order,recorded_by,event_type,reason,captured_at,received_at,capture_mode,device_id,capture_sequence,clock_offset_ms)
   values((x->>'client_event_id')::uuid,(x->>'client_event_id')::uuid,p_session_id,coalesce(a.athlete_id::text,a.legacy_athlete_id),a.name,a.bib_number,c.checkpoint_sequence,c.label,greatest(0,s.elapsed_offset_seconds+extract(epoch from captured-s.started_at)),captured,n,nullif(trim(p_recorded_by),''),case when conflict then 'pack_conflict' else 'split_recorded' end,case when conflict then 'duplicate logical split' end,captured,clock_timestamp(),'pack',x->>'device_id',(x->>'capture_sequence')::bigint,(x->>'clock_offset_ms')::numeric) returning *;
 end loop;
end $$;
grant execute on function public.record_pack_split_events(uuid,jsonb,text) to authenticated;
notify pgrst,'reload schema';
