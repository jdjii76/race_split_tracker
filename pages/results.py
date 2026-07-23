"""Results page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from split_tracker.formatting import format_duration, format_pace


def _results_frame() -> pd.DataFrame:
    rows = []
    for split in sorted(st.session_state.splits, key=lambda item: item.sequence):
        rows.append(
            {
                "Sequence": split.sequence,
                "Athlete": split.athlete_name,
                "Bib": split.bib_number,
                "Checkpoint": split.checkpoint_number,
                "Distance": split.cumulative_distance_miles,
                "Cumulative Time": format_duration(split.cumulative_time_seconds),
                "Segment Split": format_duration(split.segment_split_seconds),
                "Average Pace": format_pace(split.average_pace_seconds_per_mile),
                "Projected Finish": format_duration(split.projected_finish_seconds),
                "Target Variance": format_pace(split.target_variance_seconds_per_mile),
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    """Render the results page."""
    st.title("Results")
    frame = _results_frame()
    if frame.empty:
        st.info("No splits have been recorded yet.")
        return

    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.download_button(
        "Download CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name="race_splits.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.subheader("Athlete Split Chart")
    athlete_names = sorted(frame["Athlete"].unique())
    selected = st.selectbox("Athlete", athlete_names)
    athlete_frame = frame[frame["Athlete"] == selected].set_index("Checkpoint")[["Distance"]]
    time_frame = pd.DataFrame(
        [
            {"Checkpoint": split.checkpoint_number, "Cumulative seconds": split.cumulative_time_seconds}
            for split in st.session_state.splits
            if split.athlete_name == selected
        ]
    ).set_index("Checkpoint")
    st.line_chart(time_frame)
    st.caption(f"Distance checkpoints for {selected}: {athlete_frame['Distance'].to_dict()}")
