"""Streamlit entry point for Race Split Tracker."""

from __future__ import annotations

import streamlit as st

from pages import live_timing, meet_dashboard, meet_management, meet_setup, results
from split_tracker.branding import apply_school_theme, load_school_profile, render_school_sidebar_brand
from split_tracker.navigation import resolve_active_meet_id
from split_tracker.repository import create_repository
from split_tracker.state import initialize_persistence_state, initialize_state

school_profile, school_profile_warnings = load_school_profile(secrets=st.secrets)
st.set_page_config(page_title=school_profile.app_title, page_icon="🏃", layout="wide")
apply_school_theme(school_profile)
initialize_state(st.session_state)
initialize_persistence_state(st.session_state)
st.session_state.school_profile = school_profile

if st.session_state.repository_result is None:
    repository_result = create_repository()
    st.session_state.repository_result = repository_result
    st.session_state.repository = repository_result.repository

repository_result = st.session_state.repository_result
if st.session_state.repository is not None:
    try:
        requested_meet_id = st.query_params.get("meet") or st.session_state.active_meet_id
        st.session_state.active_meet_id = resolve_active_meet_id(
            requested_meet_id, st.session_state.repository.list_meets()
        )
        if st.session_state.active_meet_id:
            st.query_params["meet"] = st.session_state.active_meet_id
        elif "meet" in st.query_params:
            del st.query_params["meet"]
    except Exception:
        pass
with st.sidebar:
    render_school_sidebar_brand(school_profile)
    for warning in school_profile_warnings:
        st.caption(f"Branding configuration: {warning}")
    if repository_result is not None:
        st.caption(f"Storage: {repository_result.storage_label}")
        if repository_result.error:
            st.error("Supabase persistence is unavailable. Check credentials, network access, and migrations.")
        elif repository_result.is_temporary:
            st.warning("Timing-session data is temporary without Supabase configuration.")
        else:
            st.success("Supabase persistence is active.")
    if st.session_state.repository is not None:
        st.divider()
        st.caption("Current Meet")
        try:
            meets = st.session_state.repository.list_meets()
        except Exception as exc:
            meets = []
            st.error(f"Could not load meets: {exc}")
        active = next((meet for meet in meets if meet.id == st.session_state.active_meet_id), None)
        st.write(f"**{active.name if active else 'None selected'}**")
        if st.button("Change Meet", use_container_width=True):
            st.session_state.show_meet_switcher = not st.session_state.get("show_meet_switcher", False)
        if st.session_state.get("show_meet_switcher") and meets:
            ids = [meet.id for meet in meets]
            selected = st.selectbox(
                "Choose meet", ids, index=ids.index(active.id) if active else 0,
                format_func=lambda meet_id: next(meet.name for meet in meets if meet.id == meet_id),
            )
            if selected != st.session_state.active_meet_id:
                st.session_state.active_meet_id = selected
                st.session_state.selected_meet_id = selected
                st.query_params["meet"] = selected
                st.session_state.show_meet_switcher = False
                st.rerun()

MEET_DASHBOARD_PAGE = st.Page(
    meet_dashboard.render,
    title="Current Meet",
    icon="🏟️",
    url_path="meet-dashboard",
    default=True,
)
MEET_SETUP_PAGE = st.Page(
    meet_management.render,
    title="Race Setup",
    icon="📝",
    url_path="meet-setup",
)
CONFIGURE_RACE_PAGE = st.Page(
    meet_setup.render,
    title="Configure Race",
    icon="👟",
    url_path="configure-race",
)
LIVE_TIMING_PAGE = st.Page(
    live_timing.render,
    title="Live Timing",
    icon="⏱️",
    url_path="live-timing",
)
RESULTS_PAGE = st.Page(
    results.render,
    title="Results",
    icon="📊",
    url_path="results",
)

st.session_state.page_registry = {
    "meet_dashboard": MEET_DASHBOARD_PAGE,
    "meet_setup": CONFIGURE_RACE_PAGE,
    "race_setup": MEET_SETUP_PAGE,
    "live_timing": LIVE_TIMING_PAGE,
    "results": RESULTS_PAGE,
}

pages = [MEET_DASHBOARD_PAGE, MEET_SETUP_PAGE, CONFIGURE_RACE_PAGE, LIVE_TIMING_PAGE, RESULTS_PAGE]

navigation = st.navigation(pages)
navigation.run()
