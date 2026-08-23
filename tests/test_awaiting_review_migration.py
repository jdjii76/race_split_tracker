"""Lifecycle and authorization checks for awaiting-review race sessions."""
from pathlib import Path

SQL = (
    Path(__file__).resolve().parents[1]
    / "supabase/migrations/027_awaiting_review_lifecycle.sql"
).read_text(encoding="utf-8").lower()


def test_migration_adds_awaiting_review_and_timing_complete_rpc():
    assert "'awaiting_review'" in SQL
    assert "complete_race_timing(p_session_id uuid)" in SQL
    assert "status='awaiting_review'" in SQL
    assert "ended_at=v_now" in SQL


def test_timing_complete_preserves_data_and_does_not_require_resolution():
    timing_function = SQL[SQL.index("create or replace function public.complete_race_timing"):SQL.index("create or replace function public.finalize_race_session")]
    assert "delete" not in timing_function
    assert "split_events" not in timing_function
    assert "race_session_athlete_outcomes" not in timing_function


def test_timer_role_cannot_call_coach_lifecycle_or_manage_results():
    assert SQL.count("public.has_app_role(array['coach','admin'])") == 3
    assert "require_app_role(array['coach','admin'])" not in SQL
    assert "grant execute on function public.complete_race_timing(uuid) to authenticated" in SQL
    assert "revoke all on function public.complete_race_timing(uuid) from public,anon" in SQL


def test_review_results_can_be_corrected_then_finalized():
    assert "v_session.status not in ('running','paused','awaiting_review')" in SQL
    assert "v_session.status not in ('awaiting_review','completed')" in SQL
    assert "insert into public.result_events" in SQL
    assert "status='completed'" in SQL
