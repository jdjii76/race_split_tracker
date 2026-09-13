"""Focused capability and session-lifecycle tests for coach Timing Mode."""
from pathlib import Path

import pytest

from split_tracker.auth import AppIdentity
from split_tracker.timer_mode import (
    can_enter_race_day_timing_mode, change_timing_station,
    enter_race_day_timing_mode, exit_race_day_timing_mode,
    is_race_day_timing_mode, is_timing_operator,
)


@pytest.mark.parametrize("role", ["coach", "admin"])
def test_coach_and_admin_enter_without_changing_role(role):
    identity = AppIdentity("user-1", f"{role}@example.test", role)
    state = {}
    assert enter_race_day_timing_mode(state, identity)
    assert identity.role == role
    assert is_race_day_timing_mode(state, identity)
    assert is_timing_operator(state, identity)


def test_dedicated_timer_workflow_does_not_require_opt_in():
    identity = AppIdentity("timer-1", "timer@example.test", "timer")
    assert not can_enter_race_day_timing_mode(identity)
    assert is_timing_operator({}, identity)


def test_normal_coach_dashboard_is_not_a_timing_operator():
    identity = AppIdentity("coach-1", "coach@example.test", "coach")
    assert not is_timing_operator({}, identity)


def test_station_selection_survives_reruns_and_change_retains_mode():
    identity = AppIdentity("coach-1", "coach@example.test", "coach")
    state = {"race_day_timing_mode": True, "timer_mode": True,
             "timer_station_checkpoint": 2, "timer_station_last_heartbeat_at": object()}
    assert is_timing_operator(state, identity)
    assert state["timer_station_checkpoint"] == 2
    change_timing_station(state)
    assert state["race_day_timing_mode"] is True
    assert state["timer_station_checkpoint"] is None
    assert state["timer_mode"] is False
    assert state["timer_station_last_heartbeat_at"] is None


def test_exit_returns_to_coach_context_and_preserves_identity():
    identity = AppIdentity("coach-1", "coach@example.test", "coach")
    state = {"race_day_timing_mode": True, "timer_mode": True, "timer_station_checkpoint": 4}
    exit_race_day_timing_mode(state)
    assert identity.role == "coach"
    assert not is_timing_operator(state, identity)
    assert state["timer_station_checkpoint"] is None


def test_live_timing_reuses_heartbeat_and_checkpoint_scope():
    source = (Path(__file__).resolve().parents[1] / "pages/live_timing.py").read_text()
    assert "is_timing_operator(st.session_state, identity)" in source
    assert "_heartbeat_timer_station()" in source
    assert "next_checkpoint.number == station_number" in source
    assert "station_number if timer_mode else None" in source


def test_migration_extends_canonical_timer_operations_to_coach_admin():
    migration = (Path(__file__).resolve().parents[1] / "supabase/migrations/033_coach_race_day_timing_mode.sql").read_text()
    assert "public.has_app_role(array['coach','admin'])" in migration
    assert "perform public.require_app_role(array['timer'])" in migration
    assert "complete_race_timing_at_finish" in migration
