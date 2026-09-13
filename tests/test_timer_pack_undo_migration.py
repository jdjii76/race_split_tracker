"""Security assertions for station-bound timer Pack Mode undo."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/030_timer_pack_undo.sql").read_text(encoding="utf-8").lower()
COACH_SQL = (ROOT / "supabase/migrations/019_append_only_timing_corrections.sql").read_text(encoding="utf-8").lower()


def test_timer_undo_rpc_is_separate_and_least_privilege():
    assert "function public.invalidate_timer_pack_event" in SQL
    assert "security definer" in SQL
    assert "require_app_role(array['timer'])" in SQL
    assert "from public, anon" in SQL
    assert "to authenticated" in SQL
    assert "require_app_role(array['coach','admin'])" in COACH_SQL


def test_timer_undo_is_bound_to_session_station_device_and_pack_capture():
    assert "user_id=auth.uid()" in SQL
    assert "race_session_id=p_session_id" in SQL
    assert "checkpoint_number=p_checkpoint_number" in SQL
    assert "device_id=trim(p_device_id)" in SQL
    assert "capture_mode='pack'" in SQL
    assert "status in ('running','paused','awaiting_review')" in SQL


def test_timer_undo_is_append_only_and_cannot_update_or_delete_events():
    undo = SQL[SQL.index("function public.invalidate_timer_pack_event"):]
    assert "insert into public.split_events" in undo
    assert "'split_voided'" in undo
    assert "target_event_id" in undo
    assert "update public.split_events" not in undo
    assert "delete from public.split_events" not in undo
