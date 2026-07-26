"""Pure widget identity and availability checks for live athlete buttons."""

from pages.live_timing import athlete_timing_button_disabled, athlete_timing_button_key


def test_button_key_is_stable_and_checkpoint_scoped():
    assert athlete_timing_button_key("session-1", "athlete-1", 2) == "split:session-1:athlete-1:2"
    assert athlete_timing_button_key("session-1", "athlete-1", 2) == athlete_timing_button_key("session-1", "athlete-1", 2)
    assert athlete_timing_button_key("session-1", "athlete-1", 3) != athlete_timing_button_key("session-1", "athlete-1", 2)
    assert athlete_timing_button_key("session-2", "athlete-1", 2) != athlete_timing_button_key("session-1", "athlete-1", 2)


def test_button_disabled_for_ready_paused_missing_and_completed_states():
    base = dict(
        shared_unavailable=False,
        race_session_id="session",
        timer_name="Coach",
        checkpoint_number=1,
        finished=False,
        reopened=False,
    )
    assert not athlete_timing_button_disabled(clock_status="running", **base)
    assert athlete_timing_button_disabled(clock_status="not_started", **base)
    assert athlete_timing_button_disabled(clock_status="paused", **base)
    assert athlete_timing_button_disabled(clock_status="running", **(base | {"race_session_id": None}))
    assert athlete_timing_button_disabled(clock_status="running", **(base | {"checkpoint_number": None}))
    assert athlete_timing_button_disabled(clock_status="running", **(base | {"finished": True}))
