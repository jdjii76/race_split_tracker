"""Static integration checks for scheduled-start setup and timer controls."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scheduled_start_fields_are_editable_in_create_and_edit_forms():
    source = (ROOT / "pages/meet_management.py").read_text(encoding="utf-8")
    creation = source[source.index('with st.form(f"add_race_'):source.index("if not races:")]
    editing_start = source.index('with st.form(f"edit_race_')
    editing = source[editing_start:source.index('if c1.button("Open in Race Setup"', editing_start)]

    for form_source in (creation, editing):
        assert "Schedule a race start" in form_source
        assert "Scheduled start date (UTC)" in form_source
        assert "Scheduled start time (UTC)" in form_source
        assert "disabled=not" not in form_source
        assert "step=60" in form_source


def test_scheduled_start_checkbox_controls_create_and_update_persistence():
    source = (ROOT / "pages/meet_management.py").read_text(encoding="utf-8")
    creation = source[source.index('with st.form(f"add_race_'):source.index("if not races:")]
    editing_start = source.index('with st.form(f"edit_race_')
    editing = source[editing_start:source.index('if c1.button("Open in Race Setup"', editing_start)]

    assert "datetime.combine(scheduled_date, scheduled_time, tzinfo=timezone.utc)" in creation
    assert "if scheduled_enabled else None" in creation
    assert "scheduled_start=scheduled_start" in creation
    assert "datetime.combine(race_start_date, race_start_time, tzinfo=timezone.utc)" in editing
    assert "if schedule_race else None" in editing
    assert "scheduled_start=scheduled_start" in editing


def test_scheduled_start_accepts_arbitrary_minute_values():
    source = (ROOT / "pages/meet_management.py").read_text(encoding="utf-8")

    assert source.count("step=60") == 2
    assert "datetime.combine(scheduled_date, scheduled_time, tzinfo=timezone.utc)" in source
    assert "datetime.combine(race_start_date, race_start_time, tzinfo=timezone.utc)" in source


def test_timer_station_buttons_obey_computed_readiness():
    source = (ROOT / "pages/race_day_timer.py").read_text(encoding="utf-8")

    assert "option.station_is_open(checkpoint)" in source
    assert "disabled=not station_open" in source
    assert "Finish Line remains the only station that starts the race" in source
