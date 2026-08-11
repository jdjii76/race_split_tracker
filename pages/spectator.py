"""Dedicated public, read-only live race page."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from split_tracker.branding import render_school_header
from split_tracker.formatting import format_distance
from split_tracker.spectator import load_spectator_race, spectator_repository


def render() -> None:
    profile = st.session_state.school_profile
    repository = st.session_state.get("repository")
    st.markdown("<style>[data-testid='stSidebar']{display:none;} .stApp [data-testid='stMainBlockContainer']{max-width:760px;}</style>", unsafe_allow_html=True)
    if repository is None:
        render_school_header(profile, "Live Race")
        st.info("Live race data is temporarily unavailable.")
        return
    race_id = st.query_params.get("spectator_race")
    session_id = st.query_params.get("spectator_session")
    try:
        view = load_spectator_race(
            spectator_repository(repository), race_id=race_id, session_id=session_id
        )
    except Exception:
        view = None
    if view is None:
        render_school_header(profile, "Live Race")
        st.warning("Race not found.")
        return

    subtitle = view.meet.name if view.meet else profile.program_name
    render_school_header(profile, view.race.name, subtitle=subtitle, compact=True)
    st.header(f"{view.race.name} • {format_distance(view.race.distance_meters)}")
    st.markdown(f"## {view.status.upper()}")
    st.caption(f"Last updated: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    if view.session is None:
        st.info("Live results will appear when timing begins.")
        return
    if view.status == "Finished":
        st.subheader("Final Results")
        final = pd.DataFrame([
            {"Place": row["Place"], "Athlete": row["Athlete"], "Final Time": row["Final Time"], "Status": row["Status"]}
            for row in view.final_rows
        ])
        if final.empty:
            st.info("Final results are not available yet.")
        else:
            st.dataframe(final, hide_index=True, use_container_width=True)
        return

    for index, athlete in enumerate(view.athlete_rows, start=1):
        with st.container(border=True):
            st.markdown(f"### {index}. {athlete.name}")
            if athlete.team:
                st.caption(athlete.team)
            st.write(f"**{athlete.latest_checkpoint} — {athlete.cumulative_time}**")
            st.caption(f"Next: {athlete.next_checkpoint} • {athlete.status}")
    st.caption("Live splits and positions are unofficial until the race is completed.")


if hasattr(st, "fragment"):
    render = st.fragment(run_every=5)(render)
