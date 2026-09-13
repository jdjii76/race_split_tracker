"""Standalone station selection for race-day timers."""
from __future__ import annotations

import streamlit as st
from uuid import uuid4

from split_tracker.branding import render_school_header
from split_tracker.auth import sign_out
from split_tracker.formatting import format_distance, format_duration
from split_tracker.state import load_race_into_setup
from split_tracker.timer_mode import (
    TimerRaceOption, build_timer_options, configured_checkpoints,
    exit_race_day_timing_mode, is_race_day_timing_mode, is_timing_operator,
    station_label,
)
from split_tracker.timing_persistence import persisted_elapsed_seconds
from split_tracker.race_readiness import computed_race_status
from split_tracker.session_checkpoints import snapshots_to_checkpoints

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
    st.session_state.setdefault("pack_device_id", str(uuid4()))
    st.session_state.repository.assign_timer_station(
        session.id, checkpoint_number, st.session_state.pack_device_id
    )
    st.session_state.repository.heartbeat_timer_station(
        session.id, checkpoint_number, st.session_state.pack_device_id
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


def _selected_timer_card(options: list[TimerRaceOption]) -> None:
    race_id = st.session_state.get("selected_race_id")
    checkpoint_number = st.session_state.get("timer_station_checkpoint")
    option = next((item for item in options if item.race.id == race_id), None)
    if option is None or checkpoint_number is None:
        return
    checkpoint = next(
        (item for item in option.checkpoints if item.number == checkpoint_number), None
    )
    if checkpoint is None:
        return
    try:
        athlete_count = len(st.session_state.repository.list_race_athletes(option.race.id))
    except Exception:
        athlete_count = 0
    sync_status = st.session_state.get("timer_station_sync_status", "Waiting")
    if st.session_state.get("sync_error"):
        sync_status = "Connection problem"
    elif st.session_state.get("storage_connected"):
        sync_status = "Connected"
    with st.container(border=True):
        st.subheader(option.meet.name)
        st.write(f"**{option.race.name} • {format_distance(option.race.distance_meters)}**")
        st.metric("Status", option.status_label.upper())
        if option.session and option.session.started_at:
            st.metric("Race clock", format_duration(persisted_elapsed_seconds(option.session)))
        columns = st.columns(3)
        columns[0].metric("Your Station", station_label(checkpoint))
        columns[1].metric("Athletes", athlete_count)
        columns[2].metric("Sync", sync_status)
        if st.button("Open Timing", type="primary", use_container_width=True):
            st.switch_page(st.session_state.page_registry["live_timing"])
    st.subheader("Choose another station")


def _current_timer_option(repository, options: list[TimerRaceOption]) -> TimerRaceOption | None:
    """Keep the assigned race visible after capture enters review/completed state."""
    race_id = st.session_state.get("selected_race_id")
    existing = next((item for item in options if item.race.id == race_id), None)
    if existing is not None or not race_id:
        return existing
    race = repository.get_race(race_id)
    session_id = st.session_state.get("active_race_session_id")
    session = repository.get_race_session(session_id) if session_id else None
    if race is None or session is None or session.race_id != race.id:
        return None
    meet = repository.get_meet(race.meet_id)
    if meet is None:
        return None
    snapshots = repository.list_race_session_checkpoints(session.id)
    checkpoints = (
        tuple(snapshots_to_checkpoints(snapshots)) if snapshots else configured_checkpoints(race)
    )
    return TimerRaceOption(
        meet, race, session, checkpoints, computed_race_status(race, session)
    )


def render() -> None:
    identity = st.session_state.get("app_identity")
    coach_timing_mode = is_race_day_timing_mode(st.session_state, identity)
    if not is_timing_operator(st.session_state, identity):
        st.error("Race Day Timing is available only to timer, coach, and admin accounts.")
        return
    st.markdown(_STATION_BUTTON_CSS, unsafe_allow_html=True)
    render_school_header(
        st.session_state.school_profile,
        "Race Day Timer",
        subtitle="Choose your race and timing station",
        compact=True,
    )
    st.caption("Select the station where you will record runners. The Finish Line timer also starts the race.")
    if coach_timing_mode and st.button("Exit Timing Mode", use_container_width=True):
        exit_race_day_timing_mode(st.session_state)
        st.switch_page(st.session_state.page_registry["meet_dashboard"])
    if not coach_timing_mode and st.button("Sign Out", use_container_width=True):
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
    current_option = _current_timer_option(repository, options)
    display_options = options if current_option is None or current_option in options else [current_option, *options]
    if not display_options:
        st.info("No races are ready, running, or paused. Ask a coach to prepare a race, then refresh.")
        if st.button("Refresh", use_container_width=True):
            st.rerun()
        return
    _selected_timer_card(display_options)
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
