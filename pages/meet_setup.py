"""Meet setup page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from split_tracker.calculations import TRACK_DISTANCE_PRESETS, XC_DISTANCE_PRESETS, generate_checkpoints, race_distance_from_preset
from split_tracker.formatting import format_distance, format_duration, format_pace, parse_time_to_seconds
from split_tracker.models import Athlete, MeetConfig
from split_tracker.state import clear_setup, replace_setup, validate_setup

TRACK_PRESETS = [*TRACK_DISTANCE_PRESETS.keys(), "Custom"]
XC_PRESETS = [*XC_DISTANCE_PRESETS.keys(), "Custom"]


def _athletes_to_frame(athletes: list[Athlete]) -> pd.DataFrame:
    rows = [
        {
            "Athlete Name": athlete.name,
            "Bib Number": athlete.bib_number,
            "Target Finish Time": format_duration(athlete.target_finish_time_seconds) if athlete.target_finish_time_seconds else "",
            "Target Pace / Mile": format_pace(athlete.target_pace_seconds_per_mile) if athlete.target_pace_seconds_per_mile else "",
            "Group / Category": athlete.group,
            "Athlete ID": athlete.athlete_id,
        }
        for athlete in athletes
    ]
    if not rows:
        rows = [{"Athlete Name": "", "Bib Number": "", "Target Finish Time": "", "Target Pace / Mile": "", "Group / Category": "", "Athlete ID": ""}]
    return pd.DataFrame(rows)


def _frame_to_athletes(frame: pd.DataFrame, existing: list[Athlete]) -> tuple[list[Athlete], list[str]]:
    existing_by_id = {athlete.athlete_id: athlete for athlete in existing}
    athletes: list[Athlete] = []
    errors: list[str] = []
    for row_number, row in frame.fillna("").iterrows():
        name = str(row.get("Athlete Name", "")).strip()
        if not name:
            if any(str(row.get(column, "")).strip() for column in ["Bib Number", "Target Finish Time", "Target Pace / Mile", "Group / Category"]):
                errors.append(f"Row {row_number + 1}: athlete name is required.")
            continue
        target_finish_raw = str(row.get("Target Finish Time", "")).strip()
        target_pace_raw = str(row.get("Target Pace / Mile", "")).replace("/mi", "").strip()
        target_finish = parse_time_to_seconds(target_finish_raw)
        target_pace = parse_time_to_seconds(target_pace_raw)
        if target_finish_raw and target_finish is None:
            errors.append(f"Row {row_number + 1}: target finish time must be MM:SS or HH:MM:SS.")
        if target_pace_raw and target_pace is None:
            errors.append(f"Row {row_number + 1}: target pace must be MM:SS or HH:MM:SS.")
        athlete_id = str(row.get("Athlete ID", "")).strip()
        previous = existing_by_id.get(athlete_id)
        athletes.append(
            Athlete(
                name=name,
                bib_number=str(row.get("Bib Number", "")).strip(),
                target_finish_time_seconds=target_finish,
                target_pace_seconds_per_mile=target_pace,
                group=str(row.get("Group / Category", "")).strip(),
                athlete_id=previous.athlete_id if previous else athlete_id or Athlete(name=name).athlete_id,
            )
        )
    bibs = [athlete.bib_number for athlete in athletes if athlete.bib_number]
    if len(bibs) != len(set(bibs)):
        errors.append("Bib numbers must be unique when entered.")
    return athletes, errors


def _template_csv() -> bytes:
    return pd.DataFrame(
        columns=["Athlete Name", "Bib Number", "Target Finish Time", "Target Pace / Mile", "Group / Category"]
    ).to_csv(index=False).encode("utf-8")


def _config_changed_unsafely(config: MeetConfig, athletes: list[Athlete]) -> bool:
    saved = st.session_state.meet_config
    saved_ids = [(athlete.athlete_id, athlete.name, athlete.bib_number) for athlete in st.session_state.athletes]
    new_ids = [(athlete.athlete_id, athlete.name, athlete.bib_number) for athlete in athletes]
    return bool(
        st.session_state.splits
        and (
            abs(saved.race_distance_meters - config.race_distance_meters) > 0.01
            or [checkpoint.distance_meters for checkpoint in saved.checkpoints] != [checkpoint.distance_meters for checkpoint in config.checkpoints]
            or saved_ids != new_ids
        )
    )


def _checkpoint_controls(course_type: str, race_distance_meters: float) -> tuple[str, float, str, list]:
    st.subheader("Checkpoint Configuration")
    mode = st.radio("Checkpoint mode", ["Standard laps", "Fixed interval", "Custom checkpoints"], horizontal=True)
    interval_meters = 400.0
    custom_text = ""
    if mode == "Standard laps":
        if course_type == "Track":
            choice = st.selectbox("Track split tracking", ["400 m laps", "200 m splits", "Custom lap length"])
            if choice == "200 m splits":
                interval_meters = 200.0
            elif choice == "Custom lap length":
                interval_meters = st.number_input("Custom track lap length (meters)", min_value=1.0, value=400.0, step=10.0)
            else:
                interval_meters = 400.0
        else:
            choice = st.selectbox("Cross country checkpoints", ["Mile checkpoints", "Kilometer checkpoints"])
            interval_meters = 1609.344 if choice == "Mile checkpoints" else 1000.0
    elif mode == "Fixed interval":
        interval_meters = st.number_input("Fixed checkpoint interval (meters)", min_value=1.0, value=400.0 if course_type == "Track" else 1000.0, step=50.0)
    else:
        custom_text = st.text_area("Custom checkpoints", value="0.5 mile, 1 mile, 2 mile, finish" if course_type == "Cross Country" else "200 m, 400 m, finish")
    checkpoints = generate_checkpoints(
        race_distance_meters=race_distance_meters,
        mode=mode,
        interval_meters=interval_meters,
        custom_checkpoint_text=custom_text,
    )
    return mode, float(interval_meters), custom_text, checkpoints


def _render_summary(config: MeetConfig, athletes: list[Athlete]) -> None:
    st.subheader("Setup Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Meet", config.meet_name or "Missing")
    c2.metric("Race", config.race_name or "Missing")
    c3.metric("Athletes", len(athletes))
    st.write(f"**Race type:** {config.course_type}")
    st.write(f"**Distance:** {config.race_distance_label} ({config.race_distance_meters:g} m)")
    st.write(f"**Checkpoints ({len(config.checkpoints)}):** {', '.join(checkpoint.label for checkpoint in config.checkpoints)}")


def render() -> None:
    """Render the meet setup page."""
    st.title("Meet Setup")
    st.caption("Configure the race, checkpoints, and roster before moving to live timing.")
    if st.session_state.get("selected_race_id"):
        st.info("Loaded from a saved race. Phase 1 persists meet/race metadata only; roster, checkpoints, splits, and results remain session-only.")

    saved_config: MeetConfig = st.session_state.meet_config
    course_type = st.radio("Race type", ["Track", "Cross Country"], index=0 if saved_config.course_type == "Track" else 1, horizontal=True)
    presets = TRACK_PRESETS if course_type == "Track" else XC_PRESETS
    default_preset = saved_config.race_distance_label if saved_config.race_distance_label in presets else presets[0]
    col1, col2 = st.columns(2)
    with col1:
        meet_name = st.text_input("Meet name", value=saved_config.meet_name)
        race_preset = st.selectbox("Race distance preset", presets, index=presets.index(default_preset))
    with col2:
        race_name = st.text_input("Race name", value=saved_config.race_name)
        custom_distance = st.number_input("Custom race distance (meters)", min_value=1.0, value=float(saved_config.race_distance_meters), step=100.0, disabled=race_preset != "Custom")

    race_distance_meters = race_distance_from_preset(course_type, race_preset, custom_distance)
    mode, interval_meters, custom_text, checkpoints = _checkpoint_controls(course_type, race_distance_meters)
    draft_config = MeetConfig(
        meet_name=meet_name.strip(),
        race_name=race_name.strip(),
        course_type=course_type,
        race_distance_meters=race_distance_meters,
        race_distance_label=race_preset if race_preset != "Custom" else format_distance(race_distance_meters),
        checkpoint_mode=mode,
        checkpoint_interval_meters=interval_meters,
        lap_length_meters=interval_meters if course_type == "Track" and mode == "Standard laps" else saved_config.lap_length_meters,
        custom_checkpoint_text=custom_text,
        checkpoints=checkpoints,
    )

    st.subheader("Athlete Roster")
    uploaded = st.file_uploader("Import CSV roster", type=["csv"])
    roster_frame = _athletes_to_frame(st.session_state.athletes)
    if uploaded is not None:
        roster_frame = pd.read_csv(uploaded).fillna("")
        if "Athlete ID" not in roster_frame.columns:
            roster_frame["Athlete ID"] = ""
    st.download_button("Download roster template CSV", data=_template_csv(), file_name="race_roster_template.csv", mime="text/csv")
    roster = st.data_editor(
        roster_frame,
        num_rows="dynamic",
        hide_index=True,
        column_config={"Athlete ID": None},
        use_container_width=True,
    )
    athletes, roster_errors = _frame_to_athletes(roster, st.session_state.athletes)
    errors = [*roster_errors, *validate_setup(draft_config, athletes)]
    errors = list(dict.fromkeys(errors))
    unsafe_change = _config_changed_unsafely(draft_config, athletes)
    if unsafe_change:
        st.warning("Splits already exist. Changing race distance, checkpoints, or roster may make existing results inconsistent; existing splits will be preserved and recalculated where possible.")
        confirm_unsafe = st.checkbox("I understand and want to save setup changes with existing splits.")
    else:
        confirm_unsafe = True

    _render_summary(draft_config, athletes)
    if errors:
        for error in errors:
            st.error(error)

    col_save, col_start, col_clear = st.columns(3)
    save_clicked = col_save.button("Save Setup", type="primary", use_container_width=True, disabled=bool(errors) or (unsafe_change and not confirm_unsafe))
    start_clicked = col_start.button("Start Timing", use_container_width=True, disabled=bool(errors) or (unsafe_change and not confirm_unsafe))
    confirm_clear = col_clear.checkbox("Confirm clear setup")
    if col_clear.button("Clear Setup", use_container_width=True, disabled=not confirm_clear):
        clear_setup(st.session_state)
        st.rerun()

    if save_clicked or start_clicked:
        replace_setup(st.session_state, draft_config, athletes)
        st.success("Setup saved.")
        if start_clicked:
            st.switch_page(st.session_state.page_registry["live_timing"])
