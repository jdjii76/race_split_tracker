"""Contracts for migration 013's locked lifecycle state machine."""

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase/migrations/013_server_authoritative_race_lifecycle.sql"
)


def test_lifecycle_migration_locks_and_uses_server_time():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "transition_race_session" in sql
    assert "for update" in sql
    assert "clock_timestamp()" in sql
    assert "extract(epoch from (v_now - started_at))" in sql
    assert "p_elapsed" not in sql
    assert "p_started" not in sql
    assert "p_paused" not in sql
    assert "p_ended" not in sql


def test_lifecycle_migration_has_explicit_terminal_and_idempotent_rules():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    for action in ("pause", "resume", "complete", "cancel"):
        assert f"v_action = '{action}'" in sql
    assert "invalid race session transition" in sql
    assert "v_session.status = 'completed'" in sql
    assert "v_session.status = 'cancelled'" in sql
    assert "status not in ('running', 'paused')" in sql
    assert "status not in ('ready', 'running', 'paused')" in sql


def test_lifecycle_migration_is_forward_only_and_uniquely_numbered():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    migrations = sorted(MIGRATION.parent.glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in migrations]

    assert "delete from" not in sql
    assert "drop table" not in sql
    assert "public.split_events" not in sql
    assert "public.race_athletes" not in sql
    assert len(versions) == len(set(versions))
    assert MIGRATION.name.startswith("013_")
