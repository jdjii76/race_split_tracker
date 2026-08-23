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
    assert '"eligible":state.athlete.athlete_id in eligible_ids' in source
    assert 'void_ids=st.session_state.get("pack_void_ids", [])' in source
    assert "st.session_state.pack_void_ids=list" in source
    assert "expected_arrival_metadata" in source
    assert "or station_number is not None" in source
