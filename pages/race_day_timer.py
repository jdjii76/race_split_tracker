"""Standalone station selection for race-day timers."""
from __future__ import annotations

import streamlit as st

from split_tracker.branding import render_school_header
from split_tracker.auth import sign_out
from split_tracker.formatting import format_distance
from split_tracker.state import load_race_into_setup
from split_tracker.timer_mode import TimerRaceOption, build_timer_options, station_label

_STATION_BUTTON_CSS = """
<style>
:root { --kmhs-timer-green: #006633; }
div[data-testid="stButton"] > button[kind="primary"] {
    background: var(--kmhs-timer-green);
    border-color: var(--kmhs-timer-green);
    color: white;
    min-height: 4.5rem;
    border-radius: 0.85rem;
    font-size: 1.15rem;
    font-weight: 750;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    filter: brightness(0.9);
    color: white;
}
div[data-testid="stButton"] > button[kind="primary"]:focus-visible {
    outline: 3px solid var(--school-accent);
    outline-offset: 2px;
}
</style>
"""


def _select_station(option: TimerRaceOption, checkpoint_number: int) -> None:
    load_race_into_setup(st.session_state, option.meet, option.race)
    st.session_state.meet_config.checkpoints = list(option.checkpoints)
    session = option.session or st.session_state.repository.prepare_race_session(
        option.race.id, list(option.checkpoints)
    )
    st.session_state.active_race_session_id = session.id
    st.session_state.timing_restored_for_race_id = None
    st.session_state.timer_station_checkpoint = checkpoint_number
    st.session_state.timer_mode = True
    st.session_state.timer_timing_mode = "pack"
    st.session_state.pack_mode_active = True
    checkpoint = next(item for item in option.checkpoints if item.number == checkpoint_number)
    identity = st.session_state.app_identity
    st.session_state.timer_name = f"{station_label(checkpoint)} • {identity.email}"
    st.switch_page(st.session_state.page_registry["live_timing"])


def render() -> None:
    st.markdown(_STATION_BUTTON_CSS, unsafe_allow_html=True)
    render_school_header(
        st.session_state.school_profile,
        "Race Day Timer",
        subtitle="Choose your race and timing station",
        compact=True,
    )
    st.caption("Select the station where you will record runners. The Finish Line timer also starts the race.")
    if st.button("Sign Out", use_container_width=True):
        client = getattr(st.session_state.get("repository"), "client", None)
        if client is not None:
            sign_out(client)
        st.session_state.app_identity = None
        st.session_state.timer_mode = False
        st.session_state.timer_station_checkpoint = None
        st.rerun()
    repository = st.session_state.get("repository")
    if repository is None:
        st.error("Race Day Timer requires a configured Supabase connection.")
        return
    try:
        options = build_timer_options(repository)
    except Exception as exc:
        st.error(f"Could not load active races: {exc}")
        return
    if not options:
        st.info("No races are ready, running, or paused. Ask a coach to prepare a race, then refresh.")
        if st.button("Refresh", use_container_width=True):
            st.rerun()
        return
    for option in options:
        with st.container(border=True):
            st.subheader(option.race.name)
            st.write(f"**{option.meet.name}**")
            details = " • ".join(filter(None, [option.race.race_category, format_distance(option.race.distance_meters)]))
            st.caption(details)
            if option.race.scheduled_start is not None:
                st.caption(
                    f"Scheduled start: {option.race.scheduled_start.strftime('%-I:%M %p UTC')}"
                )
            st.metric("Race status", option.status_label)
            st.markdown("**Select your timing station**")
            for checkpoint in option.checkpoints:
                station_open = option.station_is_open(checkpoint)
                if st.button(
                    station_label(checkpoint),
                    key=f"timer_station:{option.race.id}:{checkpoint.number}",
                    type="primary",
                    use_container_width=True,
                    disabled=not station_open,
                ):
                    _select_station(option, checkpoint.number)
            if option.status_label == "Upcoming":
                st.caption("Finish Line can prepare now. Split stations open five minutes before the scheduled start.")
            elif option.status_label == "Ready":
                st.caption("All stations can prepare. Finish Line remains the only station that starts the race.")
