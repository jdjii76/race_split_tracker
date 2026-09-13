-- Secure coach/admin writes while preserving narrowly scoped public race reads.
-- Authorization-only migration; no race, athlete, event, or outcome rows are changed.

create table if not exists public.app_users (
    user_id uuid primary key references auth.users(id) on delete cascade,
    role text not null check (role in ('coach', 'admin')),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);
alter table public.app_users enable row level security;

create or replace function public.has_app_role(p_roles text[])
returns boolean language sql stable security definer set search_path = public, auth
as $$ select exists(select 1 from public.app_users where user_id = auth.uid() and role = any(p_roles)); $$;
create or replace function public.require_app_role(p_roles text[])
returns void language plpgsql stable security definer set search_path = public, auth
as $$ begin if auth.uid() is null or not public.has_app_role(p_roles) then raise exception 'not authorized' using errcode='42501'; end if; end; $$;

alter table public.meets enable row level security;
alter table public.races enable row level security;
alter table public.meet_templates enable row level security;
alter table public.template_races enable row level security;
alter table public.race_athletes enable row level security;
alter table public.race_sessions enable row level security;
alter table public.race_session_checkpoints enable row level security;
alter table public.split_events enable row level security;
alter table public.race_session_athlete_outcomes enable row level security;
alter table public.athletes enable row level security;
alter table public.school_profiles enable row level security;

-- Remove every development prototype policy before installing role policies.
drop policy if exists dev_anon_all_meets on public.meets;
drop policy if exists dev_anon_all_races on public.races;
drop policy if exists dev_anon_all_meet_templates on public.meet_templates;
drop policy if exists dev_anon_all_template_races on public.template_races;
drop policy if exists dev_anon_all_race_athletes on public.race_athletes;
drop policy if exists dev_anon_all_race_sessions on public.race_sessions;
drop policy if exists dev_anon_all_split_events on public.split_events;
drop policy if exists dev_anon_all_race_session_checkpoints on public.race_session_checkpoints;
drop policy if exists dev_all_race_session_athlete_outcomes on public.race_session_athlete_outcomes;
drop policy if exists dev_anon_all_athletes on public.athletes;
drop policy if exists dev_anon_all_school_profiles on public.school_profiles;

-- Coach/admin shared race operations. All authenticated accounts still need app_users membership.
create policy app_staff_meets on public.meets for all to authenticated using (public.has_app_role(array['coach','admin'])) with check (public.has_app_role(array['coach','admin']));
create policy app_staff_races on public.races for all to authenticated using (public.has_app_role(array['coach','admin'])) with check (public.has_app_role(array['coach','admin']));
create policy app_staff_templates on public.meet_templates for all to authenticated using (public.has_app_role(array['coach','admin'])) with check (public.has_app_role(array['coach','admin']));
create policy app_staff_template_races on public.template_races for all to authenticated using (public.has_app_role(array['coach','admin'])) with check (public.has_app_role(array['coach','admin']));
create policy app_staff_race_athletes on public.race_athletes for all to authenticated using (public.has_app_role(array['coach','admin'])) with check (public.has_app_role(array['coach','admin']));
create policy app_staff_race_sessions on public.race_sessions for all to authenticated using (public.has_app_role(array['coach','admin'])) with check (public.has_app_role(array['coach','admin']));
create policy app_staff_split_events on public.split_events for all to authenticated using (public.has_app_role(array['coach','admin'])) with check (public.has_app_role(array['coach','admin']));
create policy app_staff_session_checkpoints on public.race_session_checkpoints for all to authenticated using (public.has_app_role(array['coach','admin'])) with check (public.has_app_role(array['coach','admin']));
create policy app_staff_outcomes on public.race_session_athlete_outcomes for all to authenticated using (public.has_app_role(array['coach','admin'])) with check (public.has_app_role(array['coach','admin']));

-- Permanent athlete and branding administration is admin-only. Branding SELECT remains public.
create policy app_staff_athletes_read on public.athletes for select to authenticated using (public.has_app_role(array['coach','admin']));
create policy app_admin_athletes_write on public.athletes for all to authenticated using (public.has_app_role(array['admin'])) with check (public.has_app_role(array['admin']));
create policy public_school_branding_read on public.school_profiles for select to anon, authenticated using (true);
create policy app_admin_school_branding_write on public.school_profiles for all to authenticated using (public.has_app_role(array['admin'])) with check (public.has_app_role(array['admin']));
create policy app_user_read_self on public.app_users for select to authenticated using (user_id = auth.uid() or public.has_app_role(array['admin']));
create policy app_admin_manage_users on public.app_users for all to authenticated using (public.has_app_role(array['admin'])) with check (public.has_app_role(array['admin']));

-- Public views expose only spectator-safe fields. Pseudonymous competitor keys prevent raw athlete UUID disclosure.
create or replace view public.spectator_meets with (security_barrier=true) as
select id, name, meet_date, location, season, status from public.meets;
create or replace view public.spectator_races with (security_barrier=true) as
select id, meet_id, name, race_category, scheduled_start, course_type, distance_meters, checkpoint_mode, status, display_order from public.races;
create or replace view public.spectator_sessions with (security_barrier=true) as
select id, race_id, status, started_at, paused_at, ended_at, elapsed_offset_seconds, created_at, updated_at from public.race_sessions;
create or replace view public.spectator_roster with (security_barrier=true) as
select ra.race_id, md5(ra.race_id::text || ':' || ra.athlete_id::text) as athlete_id,
       ra.name, ra.team, ra.display_order, ra.active
from public.race_athletes ra;
create or replace view public.spectator_checkpoints with (security_barrier=true) as
select id, race_session_id, checkpoint_sequence, label, distance_meters, distance_unit,
       lap_number, checkpoint_type, is_finish, created_at
from public.race_session_checkpoints;
create or replace view public.spectator_split_events with (security_barrier=true) as
select md5(se.race_session_id::text || ':' || se.id::text) as id, se.race_session_id,
       md5(rs.race_id::text || ':' || se.athlete_id::text) as athlete_id,
       se.athlete_name, se.checkpoint_number, se.checkpoint_label, se.elapsed_seconds,
       se.recorded_at, se.event_order, se.created_at, se.updated_at,
       case when se.correction_type = 'manual' then 'manual' else '' end as correction_type
from public.split_events se join public.race_sessions rs on rs.id=se.race_session_id
where not se.is_deleted;
create or replace view public.spectator_outcomes with (security_barrier=true) as
select o.race_session_id, md5(rs.race_id::text || ':' || o.athlete_id::text) as athlete_id,
       o.status, o.recorded_at
from public.race_session_athlete_outcomes o join public.race_sessions rs on rs.id=o.race_session_id;

revoke all on public.meets, public.races, public.meet_templates, public.template_races,
    public.race_athletes, public.race_sessions, public.race_session_checkpoints,
    public.split_events, public.race_session_athlete_outcomes, public.athletes,
    public.app_users, public.school_profiles from anon;
grant select on public.school_profiles to anon;
grant select on public.spectator_meets, public.spectator_races, public.spectator_sessions,
    public.spectator_roster, public.spectator_checkpoints, public.spectator_split_events,
    public.spectator_outcomes to anon, authenticated;
grant select, insert, update, delete on public.meets, public.races, public.meet_templates,
    public.template_races, public.race_athletes, public.race_sessions,
    public.race_session_checkpoints, public.split_events, public.race_session_athlete_outcomes
    to authenticated;
grant select, insert, update, delete on public.athletes, public.school_profiles, public.app_users to authenticated;


-- Defense in depth: every SECURITY DEFINER mutation verifies auth.uid() application role.
create or replace function public.create_started_race_session_with_checkpoints(
    p_session_id uuid,
    p_race_id uuid,
    p_started_at timestamptz,
    p_elapsed_offset_seconds numeric,
    p_checkpoints jsonb
)
returns setof public.race_sessions
language plpgsql
as $$
begin
    perform public.require_app_role(array['coach','admin']);
    if p_checkpoints is null or jsonb_array_length(p_checkpoints) = 0 then
        raise exception 'checkpoint snapshot is required';
    end if;

    insert into public.race_sessions (id, race_id, status, started_at, elapsed_offset_seconds)
    values (p_session_id, p_race_id, 'ready', p_started_at, p_elapsed_offset_seconds)
    on conflict (id) do nothing;

    insert into public.race_session_checkpoints (
        race_session_id,
        checkpoint_sequence,
        label,
        distance_meters,
        distance_unit,
        lap_number,
        checkpoint_type,
        source_checkpoint_id,
        is_finish
    )
    select
        p_session_id,
        (item->>'checkpoint_sequence')::integer,
        item->>'label',
        (item->>'distance_meters')::numeric,
        coalesce(item->>'distance_unit', 'meters'),
        nullif(item->>'lap_number', '')::integer,
        coalesce(item->>'checkpoint_type', 'split'),
        nullif(item->>'source_checkpoint_id', ''),
        coalesce((item->>'is_finish')::boolean, false)
    from jsonb_array_elements(p_checkpoints) item
    on conflict (race_session_id, checkpoint_sequence) do nothing;

    update public.race_sessions
    set status = 'running', started_at = p_started_at, elapsed_offset_seconds = p_elapsed_offset_seconds, updated_at = timezone('utc', now())
    where id = p_session_id;

    return query select * from public.race_sessions where id = p_session_id;
end;
$$;

create or replace function public.get_or_create_active_race_session(
    p_race_id uuid,
    p_checkpoints jsonb
)
returns setof public.race_sessions
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_session public.race_sessions%rowtype;
    v_started_at timestamptz;
begin
    perform public.require_app_role(array['coach','admin']);
    -- Serialize independent application processes by race, not by a client UUID.
    perform pg_advisory_xact_lock(hashtextextended(p_race_id::text, 0));

    select *
    into v_session
    from public.race_sessions
    where race_id = p_race_id
      and status in ('ready', 'running', 'paused')
    order by created_at desc, id desc
    limit 1
    for update;

    if found and v_session.status in ('running', 'paused') then
        return query select * from public.race_sessions where id = v_session.id;
        return;
    end if;

    if p_checkpoints is null or jsonb_typeof(p_checkpoints) <> 'array'
       or jsonb_array_length(p_checkpoints) = 0 then
        raise exception 'checkpoint snapshot is required';
    end if;

    v_started_at := clock_timestamp();

    if not found then
        insert into public.race_sessions (
            race_id, status, started_at, elapsed_offset_seconds
        )
        values (p_race_id, 'running', v_started_at, 0)
        returning * into v_session;
    else
        update public.race_sessions
        set
            status = 'running',
            started_at = coalesce(started_at, v_started_at),
            paused_at = null,
            updated_at = timezone('utc', now())
        where id = v_session.id
        returning * into v_session;
    end if;

    insert into public.race_session_checkpoints (
        race_session_id,
        checkpoint_sequence,
        label,
        distance_meters,
        distance_unit,
        lap_number,
        checkpoint_type,
        source_checkpoint_id,
        is_finish
    )
    select
        v_session.id,
        (item->>'checkpoint_sequence')::integer,
        item->>'label',
        (item->>'distance_meters')::numeric,
        coalesce(item->>'distance_unit', 'meters'),
        nullif(item->>'lap_number', '')::integer,
        coalesce(item->>'checkpoint_type', 'split'),
        nullif(item->>'source_checkpoint_id', ''),
        coalesce((item->>'is_finish')::boolean, false)
    from jsonb_array_elements(p_checkpoints) item
    on conflict (race_session_id, checkpoint_sequence) do nothing;

    return query select * from public.race_sessions where id = v_session.id;
end;
$$;

create or replace function public.record_shared_split(p_event jsonb)
returns setof public.split_events
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_session public.race_sessions%rowtype;
    v_athlete public.race_athletes%rowtype;
    v_checkpoint public.race_session_checkpoints%rowtype;
    v_existing public.split_events%rowtype;
    v_session_id uuid := (p_event->>'race_session_id')::uuid;
    v_event_id uuid := coalesce((p_event->>'id')::uuid, gen_random_uuid());
    v_identity text;
    v_completed integer;
    v_order integer;
    v_recorded_at timestamptz;
    v_elapsed_seconds numeric;
begin
    perform public.require_app_role(array['coach','admin']);
    -- The session-row lock serializes progression and sequence allocation.
    select * into v_session
    from public.race_sessions
    where id = v_session_id
    for update;
    if not found then
        raise exception 'Race session not found';
    end if;
    select * into v_athlete
    from public.race_athletes
    where race_id = v_session.race_id
      and active = true
      and (
          athlete_id::text = p_event->>'athlete_id'
          or legacy_athlete_id = p_event->>'athlete_id'
      )
    limit 1;
    if not found then
        raise exception 'Invalid athlete for this race session';
    end if;
    v_identity := coalesce(v_athlete.athlete_id::text, v_athlete.legacy_athlete_id);

    -- A retry after an ambiguous HTTP response reuses its request UUID and
    -- receives the original committed row instead of advancing a checkpoint.
    select * into v_existing
    from public.split_events
    where id = v_event_id;
    if found then
        if v_existing.race_session_id <> v_session_id
           or v_existing.athlete_id <> v_identity then
            raise exception 'Split request ID belongs to a different action';
        end if;
        return query select * from public.split_events where id = v_event_id;
        return;
    end if;

    if v_session.status <> 'running' or v_session.started_at is null then
        raise exception 'Race session is not running';
    end if;

    select count(*) into v_completed
    from public.split_events
    where race_session_id = v_session_id
      and athlete_id = v_identity
      and is_deleted = false;

    select * into v_checkpoint
    from public.race_session_checkpoints
    where race_session_id = v_session_id
    order by checkpoint_sequence
    offset v_completed
    limit 1;
    if not found then
        raise exception 'Athlete has no remaining checkpoint';
    end if;
    if (p_event->>'checkpoint_number')::integer <> v_checkpoint.checkpoint_sequence then
        raise exception 'Unexpected checkpoint progression';
    end if;

    select coalesce(max(event_order), 0) + 1 into v_order
    from public.split_events
    where race_session_id = v_session_id;

    v_recorded_at := clock_timestamp();
    v_elapsed_seconds := greatest(
        0,
        v_session.elapsed_offset_seconds
        + extract(epoch from (v_recorded_at - v_session.started_at))
    );

    return query
    insert into public.split_events (
        id,
        race_session_id,
        athlete_id,
        athlete_name,
        bib_number,
        checkpoint_number,
        checkpoint_label,
        elapsed_seconds,
        recorded_at,
        event_order,
        is_deleted,
        recorded_by
    )
    values (
        v_event_id,
        v_session_id,
        v_identity,
        v_athlete.name,
        v_athlete.bib_number,
        v_checkpoint.checkpoint_sequence,
        v_checkpoint.label,
        v_elapsed_seconds,
        v_recorded_at,
        v_order,
        false,
        nullif(trim(p_event->>'recorded_by'), '')
    )
    returning *;
end;
$$;

create or replace function public.transition_race_session(
    p_session_id uuid,
    p_action text
)
returns setof public.race_sessions
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_session public.race_sessions%rowtype;
    v_action text := lower(trim(p_action));
    v_now timestamptz;
begin
    perform public.require_app_role(array['coach','admin']);
    select * into v_session
    from public.race_sessions
    where id = p_session_id
    for update;

    if not found then
        raise exception 'Race session not found';
    end if;
    if v_action not in ('pause', 'resume', 'complete', 'cancel') then
        raise exception 'Unknown race session action: %', p_action;
    end if;
    if v_session.status = 'running' and v_session.started_at is null then
        raise exception 'Running race session has no start timestamp';
    end if;

    -- Idempotent retries return the original authoritative row without
    -- changing timestamps or accumulating elapsed time a second time.
    if (v_action = 'pause' and v_session.status = 'paused')
       or (v_action = 'resume' and v_session.status = 'running')
       or (v_action = 'complete' and v_session.status = 'completed')
       or (v_action = 'cancel' and v_session.status = 'cancelled') then
        return query select * from public.race_sessions where id = p_session_id;
        return;
    end if;

    if (v_action = 'pause' and v_session.status <> 'running')
       or (v_action = 'resume' and v_session.status <> 'paused')
       or (v_action = 'complete' and v_session.status not in ('running', 'paused'))
       or (v_action = 'cancel' and v_session.status not in ('ready', 'running', 'paused')) then
        raise exception 'Invalid race session transition: % from %', v_action, v_session.status;
    end if;

    v_now := clock_timestamp();

    if v_action = 'pause' then
        update public.race_sessions
        set
            status = 'paused',
            elapsed_offset_seconds = elapsed_offset_seconds + greatest(
                0,
                extract(epoch from (v_now - started_at))
            ),
            paused_at = v_now,
            updated_at = v_now
        where id = p_session_id
        returning * into v_session;
    elsif v_action = 'resume' then
        update public.race_sessions
        set
            status = 'running',
            started_at = v_now,
            paused_at = null,
            updated_at = v_now
        where id = p_session_id
        returning * into v_session;
    elsif v_action = 'complete' then
        update public.race_sessions
        set
            status = 'completed',
            elapsed_offset_seconds = case
                when status = 'running' then elapsed_offset_seconds + greatest(
                    0,
                    extract(epoch from (v_now - started_at))
                )
                else elapsed_offset_seconds
            end,
            ended_at = v_now,
            paused_at = null,
            updated_at = v_now
        where id = p_session_id
        returning * into v_session;
    else
        update public.race_sessions
        set
            status = 'cancelled',
            elapsed_offset_seconds = case
                when status = 'running' then elapsed_offset_seconds + greatest(
                    0,
                    extract(epoch from (v_now - started_at))
                )
                else elapsed_offset_seconds
            end,
            ended_at = case when started_at is null then null else v_now end,
            paused_at = null,
            updated_at = v_now
        where id = p_session_id
        returning * into v_session;
    end if;

    return query select * from public.race_sessions where id = p_session_id;
end;
$$;

create or replace function public.delete_unused_athlete(p_athlete_id uuid)
returns boolean
language plpgsql
security invoker
set search_path = public
as $$
begin
    perform public.require_app_role(array['admin']);
    -- Locking the athlete row serializes this check with deletion. The restrictive
    -- FK remains the final safeguard if a race link is inserted concurrently.
    perform 1 from public.athletes where id = p_athlete_id for update;
    if not found then
        return false;
    end if;

    if exists (
        select 1 from public.race_athletes where athlete_id = p_athlete_id
    ) then
        raise exception 'Athlete has race history and cannot be permanently deleted'
            using errcode = '23503';
    end if;

    delete from public.athletes where id = p_athlete_id;
    return found;
end;
$$;

create or replace function public.invalidate_split_event(
    p_event_id uuid,
    p_session_id uuid,
    p_athlete_id text,
    p_checkpoint_number integer,
    p_corrected_by text default null,
    p_require_latest boolean default false
)
returns setof public.split_events
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_event public.split_events%rowtype;
begin
    perform public.require_app_role(array['coach','admin']);
    perform 1 from public.race_sessions where id = p_session_id for update;
    if not found then raise exception 'Race session not found'; end if;

    select * into v_event from public.split_events
    where id = p_event_id for update;
    if not found then raise exception 'Split event not found'; end if;
    if v_event.race_session_id <> p_session_id
       or v_event.athlete_id <> p_athlete_id
       or v_event.checkpoint_number <> p_checkpoint_number then
        raise exception 'Split correction no longer matches the selected race-session event';
    end if;
    if v_event.is_deleted then
        raise exception 'Split event was already corrected by another user';
    end if;
    if p_require_latest and exists (
        select 1 from public.split_events
        where race_session_id = p_session_id and is_deleted = false
          and event_order > v_event.event_order
    ) then
        raise exception 'A newer split was recorded; refresh before choosing Undo Last Split';
    end if;

    return query update public.split_events
    set is_deleted = true,
        correction_type = 'invalidated',
        corrected_at = clock_timestamp(),
        corrected_by = nullif(trim(p_corrected_by), ''),
        updated_at = clock_timestamp()
    where id = p_event_id
    returning *;
end;
$$;

create or replace function public.record_manual_split(p_event jsonb)
returns setof public.split_events
language plpgsql
security invoker
set search_path = public
as $$
declare
    v_session public.race_sessions%rowtype;
    v_athlete public.race_athletes%rowtype;
    v_checkpoint public.race_session_checkpoints%rowtype;
    v_candidate public.race_session_checkpoints%rowtype;
    v_existing public.split_events%rowtype;
    v_session_id uuid := (p_event->>'race_session_id')::uuid;
    v_event_id uuid := coalesce((p_event->>'id')::uuid, gen_random_uuid());
    v_identity text;
    v_checkpoint_number integer := (p_event->>'checkpoint_number')::integer;
    v_elapsed numeric := (p_event->>'elapsed_seconds')::numeric;
    v_previous numeric;
    v_later numeric;
    v_current_elapsed numeric;
    v_order integer;
begin
    perform public.require_app_role(array['coach','admin']);
    select * into v_session from public.race_sessions
    where id = v_session_id for update;
    if not found then raise exception 'Race session not found'; end if;
    if v_session.status not in ('running', 'paused') then
        raise exception 'Missed splits can only be added to a running or paused race';
    end if;

    select * into v_athlete from public.race_athletes
    where race_id = v_session.race_id and active = true
      and (athlete_id::text = p_event->>'athlete_id' or legacy_athlete_id = p_event->>'athlete_id')
    limit 1;
    if not found then raise exception 'Invalid athlete for this race session'; end if;
    v_identity := coalesce(v_athlete.athlete_id::text, v_athlete.legacy_athlete_id);

    select * into v_existing from public.split_events where id = v_event_id;
    if found then
        if v_existing.race_session_id <> v_session_id
           or v_existing.athlete_id <> v_identity
           or v_existing.checkpoint_number <> v_checkpoint_number then
            raise exception 'Split request ID belongs to a different action';
        end if;
        return query select * from public.split_events where id = v_event_id;
        return;
    end if;

    -- The only permitted insertion is the first checkpoint absent from the
    -- athlete's active history. This also permits replacing an invalidated
    -- older split while retaining later rows for deterministic replay.
    for v_candidate in
        select * from public.race_session_checkpoints
        where race_session_id = v_session_id order by checkpoint_sequence
    loop
        if not exists (
            select 1 from public.split_events
            where race_session_id = v_session_id and athlete_id = v_identity
              and checkpoint_number = v_candidate.checkpoint_sequence and is_deleted = false
        ) then
            v_checkpoint := v_candidate;
            exit;
        end if;
    end loop;
    if v_checkpoint.id is null or v_checkpoint.checkpoint_sequence <> v_checkpoint_number then
        raise exception 'Manual split must be the athlete''s next missing checkpoint';
    end if;

    select max(elapsed_seconds) into v_previous from public.split_events
    where race_session_id = v_session_id and athlete_id = v_identity and is_deleted = false
      and checkpoint_number < v_checkpoint_number;
    select min(elapsed_seconds) into v_later from public.split_events
    where race_session_id = v_session_id and athlete_id = v_identity and is_deleted = false
      and checkpoint_number > v_checkpoint_number;
    if v_elapsed < 0 or (v_previous is not null and v_elapsed <= v_previous)
       or (v_later is not null and v_elapsed >= v_later) then
        raise exception 'Manual elapsed time must fall between the athlete''s surrounding splits';
    end if;

    v_current_elapsed := v_session.elapsed_offset_seconds;
    if v_session.status = 'running' and v_session.started_at is not null then
        v_current_elapsed := v_current_elapsed + extract(epoch from (clock_timestamp() - v_session.started_at));
    end if;
    if v_elapsed > greatest(0, v_current_elapsed) then
        raise exception 'Manual elapsed time cannot be later than the authoritative race clock';
    end if;

    select coalesce(max(event_order), 0) + 1 into v_order
    from public.split_events where race_session_id = v_session_id;

    return query insert into public.split_events (
        id, race_session_id, athlete_id, athlete_name, bib_number,
        checkpoint_number, checkpoint_label, elapsed_seconds, recorded_at,
        event_order, is_deleted, recorded_by, correction_type, corrected_at, corrected_by
    ) values (
        v_event_id, v_session_id, v_identity, v_athlete.name, v_athlete.bib_number,
        v_checkpoint.checkpoint_sequence, v_checkpoint.label, v_elapsed, clock_timestamp(),
        v_order, false, nullif(trim(p_event->>'recorded_by'), ''), 'manual', clock_timestamp(),
        nullif(trim(p_event->>'recorded_by'), '')
    ) returning *;
end;
$$;

create or replace function public.set_race_athlete_dnf(
    p_session_id uuid, p_athlete_id text, p_recorded_by text default null
)
returns setof public.race_session_athlete_outcomes
language plpgsql security invoker set search_path = public as $$
declare v_session public.race_sessions%rowtype;
begin
    perform public.require_app_role(array['coach','admin']);
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
    perform public.require_app_role(array['coach','admin']);
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
    perform public.require_app_role(array['coach','admin']);
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
    perform public.require_app_role(array['coach','admin']);
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

-- PostgreSQL grants function EXECUTE to PUBLIC by default; remove that legacy path first.
revoke execute on all functions in schema public from public, anon;
grant execute on function public.has_app_role(text[]) to authenticated;
grant execute on function public.require_app_role(text[]) to authenticated;
grant execute on function public.create_started_race_session_with_checkpoints(uuid,uuid,timestamptz,numeric,jsonb) to authenticated;
grant execute on function public.get_or_create_active_race_session(uuid,jsonb) to authenticated;
grant execute on function public.record_shared_split(jsonb) to authenticated;
grant execute on function public.transition_race_session(uuid,text) to authenticated;
grant execute on function public.invalidate_split_event(uuid,uuid,text,integer,text,boolean) to authenticated;
grant execute on function public.record_manual_split(jsonb) to authenticated;
grant execute on function public.set_race_athlete_dnf(uuid,text,text) to authenticated;
grant execute on function public.clear_race_athlete_dnf(uuid,text) to authenticated;
grant execute on function public.finalize_race_session(uuid) to authenticated;
grant execute on function public.reopen_race_session(uuid) to authenticated;
grant execute on function public.delete_unused_athlete(uuid) to authenticated;
