"""Least-privilege checks for ready-session preparation."""
from pathlib import Path

SQL = (
    Path(__file__).resolve().parents[1]
    / "supabase/migrations/029_prepare_race_session.sql"
).read_text(encoding="utf-8").lower()


def test_prepare_rpc_is_validated_security_definer_for_authenticated_roles():
    assert "function public.prepare_race_session" in SQL
    assert "security definer" in SQL
    assert "require_app_role(array['coach','admin','timer'])" in SQL
    assert "grant execute on function public.prepare_race_session(uuid,jsonb) to authenticated" in SQL
    assert "from public, anon" in SQL


def test_prepare_rpc_creates_ready_session_without_start_timestamp():
    assert "values (p_race_id, 'ready', null, 0)" in SQL
    assert "status in ('ready','running','paused')" in SQL
    assert "status = 'running'" not in SQL
    assert "started_at =" not in SQL


def test_prepare_rpc_snapshots_checkpoints_without_split_writes():
    assert "insert into public.race_session_checkpoints" in SQL
    assert "on conflict (race_session_id, checkpoint_sequence) do nothing" in SQL
    assert "split_events" not in SQL
