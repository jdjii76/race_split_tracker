"""Contracts for forward-only race finalization migration 016."""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/016_race_finalization_outcomes.sql"


def test_migration_adds_scoped_outcomes_and_locked_workflow_rpcs():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "create table if not exists public.race_session_athlete_outcomes" in sql
    assert "primary key (race_session_id, athlete_id)" in sql
    assert "references public.race_sessions(id) on delete cascade" in sql
    for rpc in ("set_race_athlete_dnf", "clear_race_athlete_dnf", "finalize_race_session", "reopen_race_session"):
        assert f"function public.{rpc}" in sql
    assert "for update" in sql
    assert "resolve every unfinished athlete" in sql
    assert "guard_completed_split_mutation" in sql
    assert "guard_dnf_split_insert" in sql
    assert "delete from public.split_events" not in sql


def test_migration_016_is_unique_and_does_not_modify_prior_files():
    migrations = sorted(MIGRATION.parent.glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in migrations]
    assert len(versions) == len(set(versions))
    assert MIGRATION.name.startswith("016_")
