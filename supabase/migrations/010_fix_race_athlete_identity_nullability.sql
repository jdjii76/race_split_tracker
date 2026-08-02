-- Allow either permanent UUID identity or preserved legacy text identity.
-- Existing rows and split-event history are not updated or deleted.
alter table public.race_athletes
    alter column athlete_id drop not null,
    alter column legacy_athlete_id drop not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.race_athletes'::regclass
          and conname = 'race_athletes_identity_required'
    ) then
        alter table public.race_athletes
            add constraint race_athletes_identity_required
            check (athlete_id is not null or legacy_athlete_id is not null)
            not valid;
    end if;
end $$;

-- Validation reads existing rows without rewriting them and rejects an unsafe
-- deployment if a pre-existing row has neither identity.
alter table public.race_athletes
    validate constraint race_athletes_identity_required;

-- Retain one race membership per identity type.
create unique index if not exists race_athletes_race_permanent_unique
    on public.race_athletes(race_id, athlete_id)
    where athlete_id is not null;
create unique index if not exists race_athletes_race_legacy_unique
    on public.race_athletes(race_id, legacy_athlete_id)
    where athlete_id is null and legacy_athlete_id is not null;

-- Ask PostgREST to observe the altered nullability and constraint immediately.
notify pgrst, 'reload schema';
