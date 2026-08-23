"""Least-privilege checks for the Finish Line timer lifecycle RPC."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/028_finish_timer_end_timing.sql").read_text(
    encoding="utf-8"
).lower()
REVIEW_SQL = (ROOT / "supabase/migrations/027_awaiting_review_lifecycle.sql").read_text(
    encoding="utf-8"
).lower()


def test_finish_timer_rpc_requires_timer_role_and_finish_checkpoint():
    assert "public.has_app_role(array['timer'])" in SQL
    assert "checkpoint_sequence=p_checkpoint_number" in SQL
    assert "is_finish=true" in SQL
    assert "only the finish line timer can end race timing" in SQL


def test_finish_timer_rpc_only_transitions_to_awaiting_review():
    assert "status='awaiting_review'" in SQL
    assert "status='completed'" not in SQL
    assert "result_events" not in SQL
    assert "split_events" not in SQL
    assert "delete" not in SQL


def test_non_finish_and_anonymous_callers_have_no_execute_path():
    assert "security definer" in SQL
    assert "auth.uid() is null" in SQL
    assert "revoke all on function public.complete_race_timing_at_finish(uuid,integer) from public,anon" in SQL
    assert "grant execute on function public.complete_race_timing_at_finish(uuid,integer) to authenticated" in SQL


def test_timer_still_cannot_manage_or_finalize_results():
    assert REVIEW_SQL.count("public.has_app_role(array['coach','admin'])") == 3
    assert "public.has_app_role(array['timer'])" not in REVIEW_SQL
