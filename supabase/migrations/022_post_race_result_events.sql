-- Append-only manual and official results for completed race sessions.
create table if not exists public.result_events (
  id uuid primary key default gen_random_uuid(),
  race_session_id uuid not null references public.race_sessions(id) on delete cascade,
  athlete_id text not null,
  status text not null check (status in ('finished','dnf','dns')),
  finish_seconds numeric(12,2),
  source text not null check (source in ('live','manual','official','imported')),
  splits jsonb not null default '{}'::jsonb,
  note text,
  supersedes_id uuid references public.result_events(id) on delete restrict,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default clock_timestamp(),
  check ((status='finished' and finish_seconds>0) or (status<>'finished' and finish_seconds is null))
);
create unique index if not exists result_events_one_successor on public.result_events(supersedes_id) where supersedes_id is not null;
create index if not exists result_events_session_athlete_created on public.result_events(race_session_id,athlete_id,created_at,id);
alter table public.result_events enable row level security;
drop policy if exists result_events_coach_read on public.result_events;
create policy result_events_coach_read on public.result_events for select to authenticated using (public.has_app_role(array['coach','admin']));

create or replace function public.append_post_race_result(
 p_id uuid,p_session_id uuid,p_athlete_id text,p_status text,p_finish_seconds numeric,p_source text,
 p_splits jsonb default '{}'::jsonb,p_note text default null,p_supersedes_id uuid default null)
returns setof public.result_events language plpgsql security invoker set search_path=public as $$
declare v_session public.race_sessions%rowtype; v_current uuid; v_value numeric; v_previous numeric := 0;
begin
 perform public.require_app_role(array['coach','admin']);
 select * into v_session from public.race_sessions where id=p_session_id for update;
 if not found or v_session.status<>'completed' then raise exception 'Historical results can only be managed for a completed race'; end if;
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
grant execute on function public.append_post_race_result(uuid,uuid,text,text,numeric,text,jsonb,text,uuid) to authenticated;

-- Public readers receive canonical values only, without notes or user metadata.
create or replace function public.get_public_result_events(p_session_id uuid)
returns table(id uuid,race_session_id uuid,athlete_id text,status text,finish_seconds numeric,source text,splits jsonb,note text,supersedes_id uuid,created_by uuid,created_at timestamptz)
language sql stable security definer set search_path=public as $$
 select e.id,e.race_session_id,e.athlete_id,e.status,e.finish_seconds,e.source,e.splits,null::text,null::uuid,null::uuid,e.created_at
 from public.result_events e join public.race_sessions rs on rs.id=e.race_session_id
 where e.race_session_id=p_session_id and rs.status='completed'
 and not exists(select 1 from public.result_events n where n.supersedes_id=e.id)
$$;
grant execute on function public.get_public_result_events(uuid) to anon,authenticated;
notify pgrst,'reload schema';
