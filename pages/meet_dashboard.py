"""Race-day dashboard for the active meet."""
from __future__ import annotations
import streamlit as st
from split_tracker.navigation import get_meet_race_summaries
from split_tracker.state import load_race_into_setup


def _open_race(meet, summary) -> None:
    load_race_into_setup(st.session_state, meet, summary.race)
    if summary.session is not None:
        st.session_state.active_race_session_id = summary.session.id
        st.session_state.selected_results_session_id = summary.session.id
    st.switch_page(st.session_state.page_registry[summary.destination])


def render() -> None:
    """Render the current meet and direct race actions."""
    st.title("Current Meet")
    repository = st.session_state.repository
    if repository is None:
        st.error("Meet data is unavailable. Check the storage connection and try again.")
        return
    meet_id = st.session_state.get("active_meet_id")
    try:
        meet = repository.get_meet(meet_id) if meet_id else None
    except Exception as exc:
        st.error(f"Could not load the current meet: {exc}")
        return
    if meet is None:
        st.info("No current meet is selected. Choose or create one in Race Setup.")
        if st.button("Open Race Setup", type="primary"):
            st.switch_page(st.session_state.page_registry["race_setup"])
        return

    st.header(meet.name)
    details = [str(meet.meet_date or "Date not set")]
    if meet.location:
        details.append(meet.location)
    details.append(meet.status.title())
    st.caption(" • ".join(details))
    try:
        summaries, errors = get_meet_race_summaries(repository, meet.id)
    except Exception as exc:
        st.error(f"Could not load races for this meet: {exc}")
        return
    active = [item for item in summaries if item.status in {"running", "paused"}]
    if active:
        if len(active) > 1:
            st.warning("Multiple races are in progress. Select the race you intend to resume.")
        first = active[0]
        if st.button(f"Resume Active Race — {first.race.name}", type="primary", use_container_width=True, key=f"resume_active_{first.race.id}"):
            _open_race(meet, first)
    if not summaries:
        st.info("This meet has no races yet. Add races in Race Setup.")
    for summary in summaries:
        with st.container(border=True):
            left, right = st.columns([3, 2], vertical_alignment="center")
            left.subheader(summary.race.name)
            left.write(f"**{summary.athlete_count} athletes** • {summary.status.replace('_', ' ').title()}")
            if summary.athlete_count == 0:
                left.caption("No athletes are assigned to this race yet.")
            if right.button(summary.action_label, key=f"race_action_{summary.race.id}", type="primary", use_container_width=True):
                _open_race(meet, summary)
    for error in errors:
        st.warning(f"Some details could not be loaded for {error}")
