"""Touch-friendly race-day dashboard for the active meet."""
from __future__ import annotations

import streamlit as st

from split_tracker.branding import render_school_header
from split_tracker.config import load_public_app_url
from split_tracker.formatting import format_distance
from split_tracker.navigation import RaceDashboardSummary, dashboard_navigation_ids, get_meet_race_summaries
from split_tracker.spectator import spectator_url
from split_tracker.state import load_race_into_setup


def _open_race(meet, summary: RaceDashboardSummary) -> None:
    race_id, session_id = dashboard_navigation_ids(summary)
    if summary.session is not None and summary.session.race_id != race_id:
        st.error("This race session no longer belongs to the selected race. Refresh and try again.")
        return

    load_race_into_setup(st.session_state, meet, summary.race)
    # Always replace navigation identities together so a previous race cannot
    # leak its active session into this race in the same browser tab.
    st.session_state.selected_race_id = race_id
    st.session_state.active_race_session_id = session_id
    st.session_state.timing_restored_for_race_id = None
    if summary.category == "completed":
        st.session_state.selected_results_session_id = session_id
    st.switch_page(st.session_state.page_registry[summary.destination])


def _started_label(summary: RaceDashboardSummary) -> str:
    started_at = summary.session.started_at if summary.session else None
    return started_at.strftime("Started %-I:%M %p UTC") if started_at else "Start time unavailable"


def _race_card(meet, summary: RaceDashboardSummary, *, emphasized: bool = False) -> None:
    with st.container(border=True):
        heading = summary.race.name
        if summary.is_test:
            heading += "  ·  🧪 Test"
        st.subheader(heading)
        st.caption(format_distance(summary.race.distance_meters))
        metrics = st.columns(2)
        metrics[0].metric("Athletes", summary.athlete_count)
        metrics[1].metric("Status", summary.display_status)
        if summary.category == "running":
            st.write(_started_label(summary))
        if st.button(
            summary.action_label,
            key=f"race_day_action:{summary.race.id}:{summary.session.id if summary.session else 'none'}",
            type="primary" if emphasized else "secondary",
            use_container_width=True,
        ):
            _open_race(meet, summary)
        if summary.category == "completed" and st.button(
            "Coach Analytics", key=f"analytics:{summary.race.id}:{summary.session.id}", use_container_width=True
        ):
            st.session_state.analytics_race_id = summary.race.id
            st.session_state.analytics_session_id = summary.session.id
            st.switch_page(st.session_state.page_registry["coach_analytics"])
        with st.expander("Share Live View"):
            public_url = spectator_url(
                summary.race.id,
                base_url=load_public_app_url(secrets=st.secrets),
            )
            st.caption("Parents can follow this race without signing in.")
            st.code(
                public_url,
                language=None,
            )
            st.caption("This race link remains valid before, during, and after timing.")


def _section(meet, title: str, summaries: list[RaceDashboardSummary], *, emphasized: bool = False) -> None:
    st.subheader(title)
    if not summaries:
        st.caption("No races in this section.")
        return
    columns = st.columns(2)
    for index, summary in enumerate(summaries):
        with columns[index % 2]:
            _race_card(meet, summary, emphasized=emphasized)


def render() -> None:
    """Render current persisted race/session state with direct race actions."""
    profile = st.session_state.school_profile
    repository = st.session_state.repository
    if repository is None:
        st.error("Meet data is unavailable. Check the storage connection and try again.")
        return
    st.markdown(
        """
        <style>
        div[data-testid="stButton"] > button {
            min-height: 3.75rem;
            font-size: 1.05rem;
            font-weight: 700;
            border-radius: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    meet_id = st.session_state.get("active_meet_id")
    try:
        meet = repository.get_meet(meet_id) if meet_id else None
    except Exception as exc:
        st.error(f"Could not load the current meet: {exc}")
        return
    if meet is None:
        render_school_header(profile, f"Welcome to {profile.app_title}")
        st.info("Create the first meet to begin setting up races and athletes.")
        if st.button("Open Meets & Races", type="primary", use_container_width=True):
            st.switch_page(st.session_state.page_registry["race_setup"])
        return

    render_school_header(profile, "Race Day", subtitle=meet.name)
    heading, refresh = st.columns([4, 1], vertical_alignment="center")
    heading.header(f"{profile.short_name or 'KMHS'} Race Day")
    if refresh.button("Refresh", use_container_width=True):
        st.rerun()
    st.caption("Live persisted race and session status • refreshes every 5 seconds")
    try:
        summaries, errors = get_meet_race_summaries(repository, meet.id)
    except Exception as exc:
        st.error(f"Could not load races for this meet: {exc}")
        return

    running = [summary for summary in summaries if summary.category == "running"]
    up_next = [summary for summary in summaries if summary.category == "up_next"]
    completed = [summary for summary in summaries if summary.category == "completed"]
    awaiting_review = [summary for summary in summaries if summary.category == "awaiting_review"]
    if len(running) > 1:
        st.info("Multiple races are running. Confirm the race name before recording splits.")
    _section(meet, "🔴 RUNNING NOW", running, emphasized=True)
    st.divider()
    _section(meet, "UP NEXT", up_next)
    st.divider()
    _section(meet, "🟠 AWAITING REVIEW", awaiting_review)
    st.divider()
    _section(meet, "COMPLETED", completed)

    if not summaries:
        st.info("This meet has no races yet. Add races in Meets & Races.")
    for error in errors:
        st.warning(error)


# Reuse the app's established Streamlit fragment polling mechanism. Repository
# reads remain persisted and batched; no dashboard-specific race state is kept.
if hasattr(st, "fragment"):
    render = st.fragment(run_every=5)(render)
