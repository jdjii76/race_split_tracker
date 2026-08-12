"""Static contracts for atomic live timing correction migration 015."""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/015_live_timing_corrections.sql"


def test_correction_migration_preserves_events_and_adds_atomic_rpcs():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for column in ("correction_type", "corrected_at", "corrected_by"):
        assert f"add column if not exists {column}" in sql
    assert "invalidate_split_event(" in sql
    assert "record_manual_split(p_event jsonb)" in sql
    assert "for update" in sql
    assert "is_deleted = true" in sql
    assert "delete from public.split_events" not in sql
    assert "race_session_id = v_session_id" in sql
    assert "manual split must be the athlete''s next missing checkpoint" in sql
    assert "p_require_latest" in sql
    assert "a newer split was recorded" in sql


def test_correction_migration_is_next_unique_version():
    migrations = sorted(MIGRATION.parent.glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in migrations]
    assert len(versions) == len(set(versions))
    assert MIGRATION.name.startswith("015_")
