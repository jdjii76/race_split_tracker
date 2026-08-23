"""Static integration checks for scheduled-start setup and timer controls."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_race_management_saves_optional_scheduled_start():
    source = (ROOT / "pages/meet_management.py").read_text(encoding="utf-8")

    assert 'st.checkbox("Schedule a race start")' in source
    assert '"Scheduled start date (UTC)"' in source
    assert '"Scheduled start time (UTC)"' in source
    assert "scheduled_start=scheduled_start" in source


def test_timer_station_buttons_obey_computed_readiness():
    source = (ROOT / "pages/race_day_timer.py").read_text(encoding="utf-8")

    assert "option.station_is_open(checkpoint)" in source
    assert "disabled=not station_open" in source
    assert "Finish Line starts the race" in source
