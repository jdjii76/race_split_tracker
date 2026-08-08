"""Static contracts for server-authoritative split timing."""
from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/012_server_authoritative_split_timing.sql"


def test_rpc_owns_timestamp_elapsed_and_event_order():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "v_recorded_at := clock_timestamp()" in sql
    assert "v_session.elapsed_offset_seconds" in sql
    assert "v_recorded_at - v_session.started_at" in sql
    assert "coalesce(max(event_order), 0) + 1" in sql
    assert "(p_event->>'elapsed_seconds')" not in sql
    assert "(p_event->>'recorded_at')" not in sql
    assert "(p_event->>'checkpoint_number')::integer <> v_checkpoint.checkpoint_sequence" in sql


def test_rpc_preserves_validation_and_retry_idempotency():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "for update" in sql
    assert "race session is not running" in sql
    assert "invalid athlete for this race session" in sql
    assert "public.race_session_checkpoints" in sql
    assert "athlete has no remaining checkpoint" in sql
    assert "where id = v_event_id" in sql
    assert "split request id belongs to a different action" in sql


def test_server_timing_migration_is_next_unique_version():
    migrations = sorted(MIGRATION.parent.glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in migrations]
    assert len(versions) == len(set(versions))
    assert migrations[-1] == MIGRATION
