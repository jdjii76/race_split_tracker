-- Safe permanent-athlete archive and atomic deletion of athletes without history.
-- Race snapshots and timing history remain protected by the existing restrictive FK.

alter table public.athletes drop constraint if exists athletes_status_check;
alter table public.athletes
    add constraint athletes_status_check
    check (status in ('active', 'inactive', 'injured', 'graduated', 'archived'));

create or replace function public.delete_unused_athlete(p_athlete_id uuid)
returns boolean
language plpgsql
security invoker
set search_path = public
as $$
begin
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

grant execute on function public.delete_unused_athlete(uuid) to anon;
notify pgrst, 'reload schema';
