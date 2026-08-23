"""Static checks for the touch-friendly station assignment surface."""
from pathlib import Path


def test_station_buttons_use_kmhs_green_touch_styling():
    source = (
        Path(__file__).resolve().parents[1] / "pages/race_day_timer.py"
    ).read_text(encoding="utf-8")

    assert "--kmhs-timer-green: #006633" in source
    assert 'min-height: 4.5rem' in source
    assert 'color: white' in source
    assert 'station_label(checkpoint)' in source
    assert 'f"Time {checkpoint.label}"' not in source


def test_only_finish_line_timer_receives_start_control():
    source = (
        Path(__file__).resolve().parents[1] / "pages/live_timing.py"
    ).read_text(encoding="utf-8")

    assert "finish_line_starter" in source
    assert "checkpoint.is_finish" in source
    assert '"You are the race starter.' in source


def test_timer_defaults_to_pack_mode_and_preserves_individual_timing():
    source = (
        Path(__file__).resolve().parents[1] / "pages/live_timing.py"
    ).read_text(encoding="utf-8")
    selection_source = (
        Path(__file__).resolve().parents[1] / "pages/race_day_timer.py"
    ).read_text(encoding="utf-8")

    assert 'st.session_state.timer_timing_mode = "pack"' in selection_source
    assert "st.session_state.pack_mode_active = True" in selection_source
    assert '"Switch to Individual Timing"' in source
    assert '"Switch to Pack Mode"' in source
    assert "if timer_mode and st.session_state.get(\"timer_timing_mode\", \"pack\") == \"pack\":" in source


def test_timer_pack_grid_receives_full_stable_roster_and_void_acknowledgements():
    source = (
        Path(__file__).resolve().parents[1] / "pages/live_timing.py"
    ).read_text(encoding="utf-8")

    assert "display_states = projection.athletes" in source
    assert '"eligible":capture_allowed and' in source
    assert 'void_ids=st.session_state.get("pack_void_ids", [])' in source
    assert "st.session_state.pack_void_ids=list" in source
    assert "expected_arrival_metadata" in source
    assert "browser_states = ordered_expected_arrival_states" in source
    assert "for state in browser_states" in source
    assert "or station_number is not None" in source
    assert "Athlete capture unlocks when Finish Line starts" in source


def test_station_selection_prepares_a_ready_session_without_starting_it():
    source = (
        Path(__file__).resolve().parents[1] / "pages/race_day_timer.py"
    ).read_text(encoding="utf-8")

    assert "prepare_race_session" in source
    assert "assign_timer_station" in source
    assert "st.session_state.active_race_session_id = session.id" in source


def test_end_race_timing_requires_confirmation_and_stays_out_of_timer_mode():
    source = (
        Path(__file__).resolve().parents[1] / "pages/live_timing.py"
    ).read_text(encoding="utf-8")

    assert 'st.button("End Race Timing"' in source
    assert 'st.markdown("### End race timing?")' in source
    assert "Live capture will stop. Existing timing data will be preserved. Results can be verified and corrected later." in source
    assert "persist_timing_complete(st.session_state)" in source
    assert "if not timer_mode:" in source


def test_finish_timer_gets_end_control_but_split_timers_do_not():
    source = (
        Path(__file__).resolve().parents[1] / "pages/live_timing.py"
    ).read_text(encoding="utf-8")

    assert "def _render_finish_timer_end_control(clock, checkpoint)" in source
    assert "checkpoint is None or not checkpoint.is_finish" in source
    assert "finish_checkpoint_number=checkpoint.number" in source
    assert "_render_finish_timer_end_control(clock, checkpoint)" in source
