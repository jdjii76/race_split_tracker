"""Meet setup page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from split_tracker.formatting import format_pace, parse_pace_to_seconds
from split_tracker.models import Athlete, MeetConfig
from split_tracker.state import replace_athlete_roster


def _athletes_to_frame(athletes: list[Athlete]) -> pd.DataFrame:
    rows = [
        {
            "Athlete Name": athlete.name,
            "Bib Number": athlete.bib_number,
            "Target Pace / Mile": format_pace(athlete.target_pace_seconds_per_mile)
            if athlete.target_pace_seconds_per_mile
            else "",
            "Athlete ID": athlete.athlete_id,
        }
        for athlete in athletes
    ]
    if not rows:
        rows = [{"Athlete Name": "", "Bib Number": "", "Target Pace / Mile": "", "Athlete ID": ""}]
    return pd.DataFrame(rows)


def _frame_to_athletes(frame: pd.DataFrame, existing: list[Athlete]) -> list[Athlete]:
    existing_by_id = {athlete.athlete_id: athlete for athlete in existing}
    athletes: list[Athlete] = []
    for _, row in frame.fillna("").iterrows():
        name = str(row.get("Athlete Name", "")).strip()
        if not name:
            continue
        athlete_id = str(row.get("Athlete ID", "")).strip()
        previous = existing_by_id.get(athlete_id)
        athletes.append(
            Athlete(
                name=name,
                bib_number=str(row.get("Bib Number", "")).strip(),
                target_pace_seconds_per_mile=parse_pace_to_seconds(row.get("Target Pace / Mile", "")),
                athlete_id=previous.athlete_id if previous else athlete_id or Athlete(name=name).athlete_id,
            )
        )
    return athletes


def render() -> None:
    """Render the meet setup page."""
    st.title("Meet Setup")
    st.caption("Configure the race and maintain a touch-ready athlete roster.")

    config: MeetConfig = st.session_state.meet_config
    with st.form("meet_setup_form"):
        col1, col2 = st.columns(2)
        with col1:
            meet_name = st.text_input("Meet name", value=config.meet_name)
            course_type = st.radio("Race type", ["Track", "Cross Country"], index=0 if config.course_type == "Track" else 1)
        with col2:
            race_name = st.text_input("Race name", value=config.race_name)
            race_distance = st.number_input("Race distance (miles)", min_value=0.01, value=float(config.race_distance_miles), step=0.1)
            checkpoint_distance = st.number_input(
                "Checkpoint distance (miles)",
                min_value=0.01,
                value=float(config.checkpoint_distance_miles),
                step=0.1,
            )

        st.subheader("Athlete Roster")
        roster = st.data_editor(
            _athletes_to_frame(st.session_state.athletes),
            num_rows="dynamic",
            hide_index=True,
            column_config={
                "Athlete ID": None,
                "Target Pace / Mile": st.column_config.TextColumn(
                    "Target Pace / Mile",
                    help="Optional pace, for example 5:30 or 330 seconds.",
                ),
            },
            use_container_width=True,
        )
        submitted = st.form_submit_button("Save setup", type="primary", use_container_width=True)

    if submitted:
        if checkpoint_distance > race_distance:
            st.error("Checkpoint distance cannot exceed race distance.")
            return
        athletes = _frame_to_athletes(roster, st.session_state.athletes)
        bibs = [athlete.bib_number for athlete in athletes if athlete.bib_number]
        if len(bibs) != len(set(bibs)):
            st.error("Bib numbers must be unique.")
            return
        st.session_state.meet_config = MeetConfig(
            meet_name=meet_name.strip(),
            race_name=race_name.strip(),
            course_type=course_type,
            race_distance_miles=float(race_distance),
            checkpoint_distance_miles=float(checkpoint_distance),
        )
        replace_athlete_roster(st.session_state, athletes)
        st.success("Meet setup saved.")

    st.info(f"Roster size: {len(st.session_state.athletes)} athletes")
