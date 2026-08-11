-- Race-session-specific DNF outcomes plus guarded finalization/reopen RPCs.

create table if not exists public.race_session_athlete_outcomes (
    race_session_id uuid not null references public.race_sessions(id) on delete cascade,
    athlete_id text not null,
    status text not null check (status in ('dnf')),
    recorded_by text,
    recorded_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    primary key (race_session_id, athlete_id)
);
create index if not exists idx_race_session_athlete_outcomes_session_status
    on public.race_session_athlete_outcomes (race_session_id, status);
alter table public.race_session_athlete_outcomes enable row level security;
grant select, insert, update, delete on public.race_session_athlete_outcomes to anon, authenticated;
do $$
begin
    if not exists (select 1 from pg_policies where schemaname='public' and tablename='race_session_athlete_outcomes' and policyname='dev_all_race_session_athlete_outcomes') then
        create policy dev_all_race_session_athlete_outcomes
        on public.race_session_athlete_outcomes for all to anon, authenticated
        using (true) with check (true);
    end if;
end $$;

create or replace function public.guard_completed_split_mutation()
returns trigger language plpgsql security invoker set search_path=public as $$
begin
    if exists (select 1 from public.race_sessions where id=coalesce(new.race_session_id,old.race_session_id) and status='completed') then
        raise exception 'Reopen the race before changing split history';
    end if;
    return new;
end $$;
drop trigger if exists guard_completed_split_mutation on public.split_events;
create trigger guard_completed_split_mutation before update on public.split_events
for each row when (old.is_deleted is distinct from new.is_deleted)
execute function public.guard_completed_split_mutation();

create or replace function public.guard_dnf_split_insert()
returns trigger language plpgsql security invoker set search_path=public as $$
begin
    if exists (
        select 1 from public.race_session_athlete_outcomes
        where race_session_id=new.race_session_id and athlete_id=new.athlete_id and status='dnf'
    ) then raise exception 'Reverse DNF before recording another split'; end if;
    return new;
end $$;
drop trigger if exists guard_dnf_split_insert on public.split_events;
create trigger guard_dnf_split_insert before insert on public.split_events
for each row execute function public.guard_dnf_split_insert();

create or replace function public.set_race_athlete_dnf(
    p_session_id uuid, p_athlete_id text, p_recorded_by text default null
)
returns setof public.race_session_athlete_outcomes
language plpgsql security invoker set search_path = public as $$
declare v_session public.race_sessions%rowtype;
begin
    select * into v_session from public.race_sessions where id=p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_session.status not in ('running','paused') then raise exception 'Reopen the race before changing athlete outcomes'; end if;
    if not exists (
        select 1 from public.race_athletes ra where ra.race_id=v_session.race_id and ra.active=true
        and (ra.athlete_id::text=p_athlete_id or ra.legacy_athlete_id=p_athlete_id)
    ) then raise exception 'Athlete does not belong to this race session'; end if;
    if exists (
        select 1 from public.split_events se
        join public.race_session_checkpoints cp on cp.race_session_id=se.race_session_id
          and cp.checkpoint_sequence=se.checkpoint_number and cp.is_finish=true
        where se.race_session_id=p_session_id and se.athlete_id=p_athlete_id and se.is_deleted=false
    ) then raise exception 'A finished athlete cannot be marked DNF'; end if;
    return query insert into public.race_session_athlete_outcomes
        (race_session_id, athlete_id, status, recorded_by)
    values (p_session_id, p_athlete_id, 'dnf', nullif(trim(p_recorded_by),''))
    on conflict (race_session_id, athlete_id) do update set
        status='dnf', recorded_by=excluded.recorded_by, updated_at=clock_timestamp()
    returning *;
end $$;

create or replace function public.clear_race_athlete_dnf(p_session_id uuid, p_athlete_id text)
returns boolean language plpgsql security invoker set search_path = public as $$
declare v_status text;
begin
    select status into v_status from public.race_sessions where id=p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_status not in ('running','paused') then raise exception 'Reopen the race before changing athlete outcomes'; end if;
    delete from public.race_session_athlete_outcomes
    where race_session_id=p_session_id and athlete_id=p_athlete_id and status='dnf';
    return found;
end $$;

create or replace function public.finalize_race_session(p_session_id uuid)
returns setof public.race_sessions
language plpgsql security invoker set search_path = public as $$
declare v_session public.race_sessions%rowtype; v_now timestamptz;
begin
    select * into v_session from public.race_sessions where id=p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_session.status='completed' then
        return query select * from public.race_sessions where id=p_session_id; return;
    end if;
    if v_session.status not in ('running','paused') then raise exception 'Race session cannot be finished from its current state'; end if;
    if exists (
        select 1 from public.race_athletes ra
        where ra.race_id=v_session.race_id and ra.active=true
        and not exists (
            select 1 from public.split_events se
            join public.race_session_checkpoints cp on cp.race_session_id=se.race_session_id
              and cp.checkpoint_sequence=se.checkpoint_number and cp.is_finish=true
            where se.race_session_id=p_session_id and se.is_deleted=false
              and se.athlete_id=coalesce(ra.athlete_id::text, ra.legacy_athlete_id)
        )
        and not exists (
            select 1 from public.race_session_athlete_outcomes o
            where o.race_session_id=p_session_id and o.athlete_id=coalesce(ra.athlete_id::text, ra.legacy_athlete_id) and o.status='dnf'
        )
    ) then raise exception 'Resolve every unfinished athlete before finishing the race'; end if;
    v_now:=clock_timestamp();
    update public.race_sessions set
        status='completed',
        elapsed_offset_seconds=case when status='running' then elapsed_offset_seconds+greatest(0,extract(epoch from(v_now-started_at))) else elapsed_offset_seconds end,
        ended_at=v_now, paused_at=null, updated_at=v_now
    where id=p_session_id returning * into v_session;
    return query select * from public.race_sessions where id=p_session_id;
end $$;

create or replace function public.reopen_race_session(p_session_id uuid)
returns setof public.race_sessions
language plpgsql security invoker set search_path = public as $$
declare v_session public.race_sessions%rowtype; v_now timestamptz;
begin
    select * into v_session from public.race_sessions where id=p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_session.status in ('running','paused') then
        return query select * from public.race_sessions where id=p_session_id; return;
    end if;
    if v_session.status<>'completed' then raise exception 'Only a completed race session can be reopened'; end if;
    v_now:=clock_timestamp();
    update public.race_sessions set status='paused', ended_at=null, paused_at=v_now, updated_at=v_now
    where id=p_session_id returning * into v_session;
    return query select * from public.race_sessions where id=p_session_id;
end $$;

grant execute on function public.set_race_athlete_dnf(uuid,text,text) to anon, authenticated;
grant execute on function public.clear_race_athlete_dnf(uuid,text) to anon, authenticated;
grant execute on function public.finalize_race_session(uuid) to anon, authenticated;
grant execute on function public.reopen_race_session(uuid) to anon, authenticated;
notify pgrst, 'reload schema';
