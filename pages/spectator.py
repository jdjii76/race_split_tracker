"""Dedicated public, read-only live race page."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape

import pandas as pd
import streamlit as st

from split_tracker.branding import render_school_header
from split_tracker.formatting import format_distance
from split_tracker.spectator import load_spectator_race, spectator_repository


def _athlete_card_html(index: int, athlete) -> str:
    """Group the public athlete name, authoritative time, and progress."""
    name = escape(athlete.name)
    team = escape(athlete.team)
    checkpoint = escape(athlete.latest_checkpoint)
    next_checkpoint = escape(athlete.next_checkpoint)
    cumulative = escape(athlete.cumulative_time)
    status = escape(athlete.status)
    if athlete.status == "DNF":
        primary = "DNF"
        detail = f"{checkpoint} · {cumulative}"
    elif athlete.status == "Finished":
        primary = cumulative
        detail = "FINISHED"
    else:
        primary = cumulative
        detail = f"{checkpoint} · Next: {next_checkpoint} · {status}"
    team_line = f'<div class="spectator-team">{team}</div>' if team else ""
    return (
        '<div class="spectator-athlete-card">'
        '<div class="spectator-athlete-top">'
        f'<div class="spectator-athlete-name">{index}. {name}</div>'
        f'<div class="spectator-athlete-time">{primary}</div>'
        '</div>'
        f'{team_line}<div class="spectator-athlete-progress">{detail}</div>'
        '</div>'
    )


def render() -> None:
    profile = st.session_state.school_profile
    repository = st.session_state.get("repository")
    st.markdown("""
        <style>
        [data-testid='stSidebar']{display:none;}
        .stApp [data-testid='stMainBlockContainer']{max-width:760px;}
        .spectator-athlete-card{border:1px solid rgba(128,128,128,.35);border-radius:.8rem;padding:.8rem 1rem;margin:.55rem 0;}
        .spectator-athlete-top{display:flex;align-items:baseline;justify-content:space-between;gap:.75rem;}
        .spectator-athlete-name{font-size:1.15rem;font-weight:750;line-height:1.25;min-width:0;}
        .spectator-athlete-time{font-size:1.55rem;font-weight:800;line-height:1;white-space:nowrap;}
        .spectator-athlete-progress{font-size:.95rem;margin-top:.35rem;}
        .spectator-team{font-size:.8rem;opacity:.72;margin-top:.15rem;}
        @media(max-width:430px){.spectator-athlete-card{padding:.72rem .8rem}.spectator-athlete-name{font-size:1.05rem}.spectator-athlete-time{font-size:1.4rem}}
        </style>
        """, unsafe_allow_html=True)
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
        st.markdown(_athlete_card_html(index, athlete), unsafe_allow_html=True)
    st.caption("Live splits and positions are unofficial until the race is completed.")


if hasattr(st, "fragment"):
    render = st.fragment(run_every=5)(render)
