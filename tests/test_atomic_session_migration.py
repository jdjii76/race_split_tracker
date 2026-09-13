"""Static contracts for atomic active race-session creation."""
from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/011_atomic_active_race_session.sql"


def test_atomic_session_migration_has_unique_rule_and_serialized_rpc():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "race_sessions_one_active_per_race" in sql
    assert "where status in ('ready', 'running', 'paused')" in sql
    assert "get_or_create_active_race_session" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "clock_timestamp()" in sql
    assert "on conflict (race_session_id, checkpoint_sequence) do nothing" in sql


def test_atomic_session_migration_preserves_history_and_data_domains():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "delete from" not in sql
    assert "drop table" not in sql
    assert "drop index" not in sql
    assert "public.athletes" not in sql
    assert "public.race_athletes" not in sql
    assert "public.split_events" not in sql


def test_atomic_session_migration_keeps_its_unique_version():
    migrations = sorted(MIGRATION.parent.glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in migrations]
    assert len(versions) == len(set(versions))
    assert MIGRATION in migrations
    assert MIGRATION.name.startswith("011_")
