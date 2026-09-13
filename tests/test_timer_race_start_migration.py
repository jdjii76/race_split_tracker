"""Authorization checks for the finish-line timer race-start migration."""
from pathlib import Path


def test_timer_start_uses_validated_rpc_without_direct_lifecycle_policy():
    sql = (
        Path(__file__).resolve().parents[1]
        / "supabase/migrations/025_timer_race_start.sql"
    ).read_text(encoding="utf-8").lower()

    assert "get_or_create_active_race_session(uuid, jsonb)" in sql
    assert "security definer" in sql
    assert "create policy" not in sql
    assert "grant insert" not in sql
    assert "grant update" not in sql
