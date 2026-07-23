"""Live timing page."""

from __future__ import annotations

import streamlit as st

from split_tracker.formatting import format_duration, format_pace
from split_tracker.state import elapsed_seconds, end_race, pause_race, record_split, reset_race, resume_race, start_race, undo_last_split


_BUTTON_CSS = """
<style>
div[data-testid="stButton"] > button {
    min-height: 4.5rem;
    font-size: 1.15rem;
    font-weight: 700;
    border-radius: 0.9rem;
    white-space: normal;
}
[data-testid="stMetricValue"] { font-size: 2.75rem; }
</style>
"""


def render() -> None:
    """Render the live timing page."""
    st.markdown(_BUTTON_CSS, unsafe_allow_html=True)
    st.title("Live Timing")

    config = st.session_state.meet_config
    clock = st.session_state.race_clock
    elapsed = elapsed_seconds(clock)
    st.metric("Race Clock", format_duration(elapsed))
    st.caption(f"{config.meet_name or 'Untitled meet'} • {config.race_name or 'Untitled race'}")

    control_cols = st.columns(5)
    if control_cols[0].button("Start", use_container_width=True, disabled=clock.status == "running"):
        start_race(st.session_state)
        st.rerun()
    if control_cols[1].button("Pause", use_container_width=True, disabled=clock.status != "running"):
        pause_race(st.session_state)
        st.rerun()
    if control_cols[2].button("Resume", use_container_width=True, disabled=clock.status != "paused"):
        resume_race(st.session_state)
        st.rerun()
    if control_cols[3].button("End", use_container_width=True, disabled=clock.status not in {"running", "paused"}):
        end_race(st.session_state)
        st.rerun()
    if control_cols[4].button("Reset", use_container_width=True):
        reset_race(st.session_state)
        st.rerun()

    if st.button("Undo last split", use_container_width=True):
        undo_last_split(st.session_state)
        st.rerun()

    if st.session_state.message:
        st.info(st.session_state.message)

    st.subheader("Athlete Buttons")
    if not st.session_state.athletes:
        st.warning("Add athletes on the Meet Setup page before timing a race.")
        return

    columns_per_row = 2 if len(st.session_state.athletes) <= 8 else 3
    for index, athlete in enumerate(st.session_state.athletes):
        if index % columns_per_row == 0:
            cols = st.columns(columns_per_row)
        label = f"{athlete.name}\nBib {athlete.bib_number or '—'}"
        if cols[index % columns_per_row].button(label, key=f"tap_{athlete.athlete_id}", use_container_width=True):
            record_split(st.session_state, athlete.athlete_id)
            st.rerun()

    st.subheader("Recent Splits")
    recent = sorted(st.session_state.splits, key=lambda split: split.sequence, reverse=True)[:8]
    if not recent:
        st.caption("No splits recorded yet.")
        return
    for split in recent:
        st.write(
            f"**{split.athlete_name}** — CP {split.checkpoint_number}: "
            f"{format_duration(split.cumulative_time_seconds)} "
            f"({format_duration(split.segment_split_seconds)} segment, {format_pace(split.average_pace_seconds_per_mile)})"
        )
