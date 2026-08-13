-- Append-only correction history for race-day mistake recovery.
alter table public.split_events add column if not exists event_type text not null default 'split_recorded';
alter table public.split_events add column if not exists target_event_id uuid references public.split_events(id) on delete restrict;
alter table public.split_events add column if not exists corrects_event_id uuid references public.split_events(id) on delete restrict;
alter table public.split_events add column if not exists reason text null;
alter table public.split_events add constraint split_events_event_type_check
  check (event_type in ('split_recorded','split_voided','split_corrected','split_manual'));
create unique index if not exists idx_split_events_one_void_per_target on public.split_events(target_event_id) where event_type='split_voided';
create index if not exists idx_split_events_session_event_type_order on public.split_events(race_session_id,event_type,event_order);
create index if not exists idx_split_events_corrects on public.split_events(corrects_event_id) where corrects_event_id is not null;

create or replace function public.invalidate_split_event(p_event_id uuid,p_session_id uuid,p_athlete_id text,p_checkpoint_number integer,p_corrected_by text default null,p_require_latest boolean default false)
returns setof public.split_events language plpgsql security invoker set search_path=public as $$
declare v public.split_events%rowtype; v_order integer;
begin
 perform public.require_app_role(array['coach','admin']);
 perform 1 from public.race_sessions where id=p_session_id for update; if not found then raise exception 'Race session not found'; end if;
 select * into v from public.split_events where id=p_event_id and race_session_id=p_session_id and athlete_id=p_athlete_id and checkpoint_number=p_checkpoint_number for update;
 if not found then raise exception 'Split correction no longer matches the selected race-session event'; end if;
 if v.is_deleted or v.event_type='split_voided' or exists(select 1 from public.split_events where target_event_id=v.id and event_type='split_voided') then raise exception 'This timing event was already changed by another coach'; end if;
 if p_require_latest and exists(select 1 from public.split_events e where e.race_session_id=p_session_id and e.event_order>v.event_order and e.event_type<>'split_voided' and not e.is_deleted and not exists(select 1 from public.split_events x where x.target_event_id=e.id and x.event_type='split_voided')) then raise exception 'A newer split was recorded; refresh before choosing Undo Last Split'; end if;
 select coalesce(max(event_order),0)+1 into v_order from public.split_events where race_session_id=p_session_id;
 return query insert into public.split_events(race_session_id,athlete_id,athlete_name,bib_number,checkpoint_number,checkpoint_label,elapsed_seconds,recorded_at,event_order,recorded_by,correction_type,corrected_at,corrected_by,event_type,target_event_id,reason)
 values(p_session_id,v.athlete_id,v.athlete_name,v.bib_number,v.checkpoint_number,v.checkpoint_label,v.elapsed_seconds,clock_timestamp(),v_order,nullif(trim(p_corrected_by),''),'invalidated',clock_timestamp(),nullif(trim(p_corrected_by),''),'split_voided',v.id,'undo') returning *;
end $$;

create or replace function public.correct_split_athlete(p_event_id uuid,p_session_id uuid,p_athlete_id text,p_checkpoint_number integer,p_new_athlete_id text,p_corrected_by text,p_request_id uuid)
returns setof public.split_events language plpgsql security invoker set search_path=public as $$
declare v public.split_events%rowtype; a public.race_athletes%rowtype; voidrow public.split_events%rowtype;
begin
 perform public.require_app_role(array['coach','admin']);
 select * into v from public.split_events where id=p_event_id and race_session_id=p_session_id and athlete_id=p_athlete_id and checkpoint_number=p_checkpoint_number for update;
 if not found then raise exception 'Split correction no longer matches the selected race-session event'; end if;
 select ra.* into a from public.race_athletes ra join public.race_sessions rs on rs.race_id=ra.race_id where rs.id=p_session_id and ra.active and (ra.athlete_id::text=p_new_athlete_id or ra.legacy_athlete_id=p_new_athlete_id) limit 1;
 if not found then raise exception 'Invalid athlete for this race session'; end if;
 if exists(select 1 from public.split_events e where e.race_session_id=p_session_id and e.athlete_id=p_new_athlete_id and e.checkpoint_number=p_checkpoint_number and not e.is_deleted and e.event_type<>'split_voided' and not exists(select 1 from public.split_events x where x.target_event_id=e.id and x.event_type='split_voided')) then raise exception '% already has this checkpoint split',a.name; end if;
 select * into voidrow from public.invalidate_split_event(p_event_id,p_session_id,p_athlete_id,p_checkpoint_number,p_corrected_by,false);
 return next voidrow;
 return query insert into public.split_events(id,race_session_id,athlete_id,athlete_name,bib_number,checkpoint_number,checkpoint_label,elapsed_seconds,recorded_at,event_order,recorded_by,correction_type,corrected_at,corrected_by,event_type,corrects_event_id,reason)
 values(p_request_id,p_session_id,coalesce(a.athlete_id::text,a.legacy_athlete_id),a.name,a.bib_number,v.checkpoint_number,v.checkpoint_label,v.elapsed_seconds,v.recorded_at,voidrow.event_order+1,nullif(trim(p_corrected_by),''),'manual',clock_timestamp(),nullif(trim(p_corrected_by),''),'split_corrected',v.id,'wrong athlete') returning *;
end $$;
grant execute on function public.invalidate_split_event(uuid,uuid,text,integer,text,boolean), public.correct_split_athlete(uuid,uuid,text,integer,text,text,uuid) to authenticated;
notify pgrst,'reload schema';

create or replace function public.classify_split_event() returns trigger language plpgsql as $$
begin
 if new.event_type='split_recorded' and new.correction_type='manual' then new.event_type='split_manual'; end if;
 return new;
end $$;
drop trigger if exists classify_split_event on public.split_events;
create trigger classify_split_event before insert on public.split_events for each row execute function public.classify_split_event();

create or replace view public.spectator_split_events with (security_barrier=true) as
select md5(se.race_session_id::text || ':' || se.id::text) as id, se.race_session_id,
       md5(rs.race_id::text || ':' || se.athlete_id::text) as athlete_id,
       se.athlete_name,se.checkpoint_number,se.checkpoint_label,se.elapsed_seconds,
       se.recorded_at,se.event_order,se.created_at,se.updated_at,
       case when se.correction_type='manual' then 'manual' else '' end as correction_type,
       se.event_type,
       case when se.target_event_id is null then null else md5(se.race_session_id::text || ':' || se.target_event_id::text) end as target_event_id,
       case when se.corrects_event_id is null then null else md5(se.race_session_id::text || ':' || se.corrects_event_id::text) end as corrects_event_id
from public.split_events se join public.race_sessions rs on rs.id=se.race_session_id
where not se.is_deleted;
grant select on public.spectator_split_events to anon,authenticated;
