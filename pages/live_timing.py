"""Live timing page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from split_tracker.calculations import athlete_finished, next_checkpoint
from split_tracker.formatting import format_distance, format_duration, format_pace
from split_tracker.state import (
    elapsed_seconds,
    end_race,
    is_athlete_finished,
    pause_race,
    record_split,
    reopen_athlete,
    reset_race,
    resume_race,
    setup_is_valid,
    start_race,
    undo_last_split,
)

_BUTTON_CSS = """
<style>
div[data-testid="stButton"] > button {
    min-height: 5rem;
    font-size: 1.05rem;
    font-weight: 700;
    border-radius: 0.9rem;
    white-space: pre-wrap;
}
[data-testid="stMetricValue"] { font-size: 2.7rem; }
.finished-athlete { opacity: 0.65; }
</style>
"""

STATUS_LABELS = {
    "not_started": "Ready",
    "running": "Running",
    "paused": "Paused",
    "ended": "Finished",
}


def _clock_metric() -> None:
    st.metric("Race Clock", format_duration(elapsed_seconds(st.session_state.race_clock)))


if hasattr(st, "fragment"):
    _clock_metric = st.fragment(run_every=1)(_clock_metric)


def _last_split_for(athlete_id: str):
    splits = [split for split in st.session_state.splits if split.athlete_id == athlete_id]
    return max(splits, key=lambda split: split.sequence) if splits else None


def _athlete_button_label(athlete) -> str:
    last = _last_split_for(athlete.athlete_id)
    checkpoints = st.session_state.meet_config.checkpoints
    next_cp = next_checkpoint([split for split in st.session_state.splits if split.athlete_id == athlete.athlete_id], checkpoints)
    finished = is_athlete_finished(st.session_state, athlete.athlete_id)
    target = ""
    if last and last.target_variance_seconds is not None:
        direction = "behind" if last.target_variance_seconds > 0 else "ahead"
        target = f"\n{format_duration(abs(last.target_variance_seconds))} {direction} target"
    status = "FINISHED" if finished else f"Next: {next_cp.label if next_cp else '—'}"
    last_line = ""
    if last:
        last_line = f"\nLast: {format_duration(last.segment_split_seconds)} • Cum: {format_duration(last.cumulative_time_seconds)}"
    return f"{athlete.name}\nBib {athlete.bib_number or '—'} • {status}{last_line}{target}"


def _live_board_frame(filter_value: str) -> pd.DataFrame:
    rows = []
    for athlete in st.session_state.athletes:
        splits = [split for split in st.session_state.splits if split.athlete_id == athlete.athlete_id]
        latest = max(splits, key=lambda split: split.sequence) if splits else None
        finished = athlete_finished(splits, st.session_state.meet_config.checkpoints)
        if filter_value == "Active" and finished:
            continue
        if filter_value == "Finished" and not finished:
            continue
        rows.append(
            {
                "Athlete": athlete.name,
                "Bib": athlete.bib_number,
                "Latest checkpoint": latest.checkpoint_label if latest else "—",
                "Checkpoint order": latest.checkpoint_number if latest else 0,
                "Latest segment": format_duration(latest.segment_split_seconds) if latest else "—",
                "Cumulative time": format_duration(latest.cumulative_time_seconds) if latest else "—",
                "Target variance": format_duration(latest.target_variance_seconds) if latest and latest.target_variance_seconds is not None else "—",
                "Finish status": "Finished" if finished else "Active",
                "Sort time": latest.cumulative_time_seconds if latest else float("inf"),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.sort_values(["Checkpoint order", "Sort time"], ascending=[False, True])
    return frame.drop(columns=["Checkpoint order", "Sort time"])


def render() -> None:
    """Render the live timing page."""
    st.markdown(_BUTTON_CSS, unsafe_allow_html=True)
    config = st.session_state.meet_config
    clock = st.session_state.race_clock
    valid_setup = setup_is_valid(st.session_state)
    status = STATUS_LABELS[clock.status]

    st.title("Live Timing")
    h1, h2, h3 = st.columns([2, 1, 1])
    h1.subheader(f"{config.meet_name or 'Meet required'} • {config.race_name or 'Race required'}")
    h2.metric("Distance", format_distance(config.race_distance_meters))
    h3.metric("Splits", len(st.session_state.splits))
    st.caption(f"Status: **{status}** • Checkpoints: {len(config.checkpoints)}")
    _clock_metric()

    if not valid_setup:
        st.warning("Complete Meet Setup before starting the race. Meet name, race name, checkpoints, and at least one athlete are required.")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    if c1.button("Start", use_container_width=True, disabled=not valid_setup or clock.status == "running" or (clock.status == "ended" and bool(st.session_state.splits))):
        start_race(st.session_state)
        st.rerun()
    if c2.button("Pause", use_container_width=True, disabled=clock.status != "running"):
        pause_race(st.session_state)
        st.rerun()
    if c3.button("Resume", use_container_width=True, disabled=clock.status != "paused"):
        resume_race(st.session_state)
        st.rerun()

    confirm_end = c4.checkbox("Confirm end")
    if c4.button("End Race", use_container_width=True, disabled=clock.status not in {"running", "paused"} or not confirm_end):
        end_race(st.session_state)
        st.rerun()

    last_split = max(st.session_state.splits, key=lambda split: split.sequence) if st.session_state.splits else None
    if last_split:
        c5.caption(f"Undo: {last_split.athlete_name} {last_split.checkpoint_label}")
    confirm_undo = c5.checkbox("Confirm undo")
    if c5.button("Undo Last Tap", use_container_width=True, disabled=not last_split or not confirm_undo):
        undo_last_split(st.session_state)
        st.rerun()

    confirm_reset = c6.checkbox("Confirm reset")
    if c6.button("Reset Race", use_container_width=True, disabled=not confirm_reset):
        reset_race(st.session_state)
        st.rerun()

    pending = st.session_state.pending_duplicate
    if pending:
        athlete = next((item for item in st.session_state.athletes if item.athlete_id == pending["athlete_id"]), None)
        if athlete:
            st.warning(f"Duplicate tap detected for {athlete.name} within 2 seconds.")
            if st.button("Record Anyway", use_container_width=True):
                record_split(st.session_state, athlete.athlete_id, now=pending["recorded_at"], record_anyway=True)
                st.rerun()

    if st.session_state.message:
        st.info(st.session_state.message)

    st.subheader("Athlete Timing Buttons")
    if not st.session_state.athletes:
        st.warning("Add athletes on the Meet Setup page before timing a race.")
        return

    columns_per_row = 2 if len(st.session_state.athletes) <= 10 else 3
    for index, athlete in enumerate(st.session_state.athletes):
        if index % columns_per_row == 0:
            cols = st.columns(columns_per_row)
        finished = is_athlete_finished(st.session_state, athlete.athlete_id)
        disabled = clock.status != "running" or (finished and not athlete.reopened_after_finish)
        with cols[index % columns_per_row]:
            if st.button(_athlete_button_label(athlete), key=f"tap_{athlete.athlete_id}", use_container_width=True, disabled=disabled):
                record_split(st.session_state, athlete.athlete_id)
                st.rerun()
            if finished and st.button("Reopen athlete", key=f"reopen_{athlete.athlete_id}", use_container_width=True):
                reopen_athlete(st.session_state, athlete.athlete_id)
                st.rerun()

    if st.session_state.athletes and all(is_athlete_finished(st.session_state, athlete.athlete_id) for athlete in st.session_state.athletes):
        st.success("Race complete: all athletes have reached the finish.")
        if st.button("Go to Results", use_container_width=True):
            st.switch_page("pages/results.py")

    st.subheader("Live Split Board")
    filter_value = st.selectbox("Filter", ["All athletes", "Active", "Finished"], label_visibility="collapsed")
    board = _live_board_frame(filter_value)
    if board.empty:
        st.caption("No athletes match this filter.")
    else:
        st.dataframe(board, hide_index=True, use_container_width=True)
