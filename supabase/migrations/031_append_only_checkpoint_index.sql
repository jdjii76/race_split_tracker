-- The original partial unique index predates append-only correction events.
-- A split_voided row intentionally shares its target's session, athlete, and
-- checkpoint, so logical uniqueness is enforced by the locked RPCs instead.
drop index if exists public.split_events_one_active_checkpoint;

create index if not exists idx_split_events_session_athlete_checkpoint_lookup
    on public.split_events (race_session_id, athlete_id, checkpoint_number);

notify pgrst, 'reload schema';
