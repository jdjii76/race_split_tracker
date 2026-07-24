"""Streamlit entry point for Race Split Tracker."""

from __future__ import annotations

import streamlit as st

from pages import live_timing, meet_dashboard, meet_setup, results
from split_tracker.repository import create_repository
from split_tracker.state import initialize_persistence_state, initialize_state

st.set_page_config(page_title="Race Split Tracker", page_icon="⏱️", layout="wide")
initialize_state(st.session_state)
initialize_persistence_state(st.session_state)

if st.session_state.repository_result is None:
    repository_result = create_repository()
    st.session_state.repository_result = repository_result
    st.session_state.repository = repository_result.repository

repository_result = st.session_state.repository_result
with st.sidebar:
    if repository_result is not None:
        st.caption(f"Storage: {repository_result.storage_label}")
        if repository_result.error:
            st.error("Supabase persistence is unavailable. Check credentials, network access, and migrations.")
        elif repository_result.is_temporary:
            st.warning("Timing-session data is temporary without Supabase configuration.")
        else:
            st.success("Supabase persistence is active.")

MEET_DASHBOARD_PAGE = st.Page(
    meet_dashboard.render,
    title="Meet Dashboard",
    icon="🏟️",
    url_path="meet-dashboard",
    default=True,
)
MEET_SETUP_PAGE = st.Page(
    meet_setup.render,
    title="Meet Setup",
    icon="📝",
    url_path="meet-setup",
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
    "meet_setup": MEET_SETUP_PAGE,
    "live_timing": LIVE_TIMING_PAGE,
    "results": RESULTS_PAGE,
}

pages = [MEET_DASHBOARD_PAGE, MEET_SETUP_PAGE, LIVE_TIMING_PAGE, RESULTS_PAGE]

navigation = st.navigation(pages)
navigation.run()
