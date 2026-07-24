"""Streamlit entry point for Race Split Tracker."""

from __future__ import annotations

import streamlit as st

from pages import live_timing, meet_setup, results
from split_tracker.state import initialize_state

st.set_page_config(page_title="Race Split Tracker", page_icon="⏱️", layout="wide")
initialize_state(st.session_state)

MEET_SETUP_PAGE = st.Page(
    meet_setup.render,
    title="Meet Setup",
    icon="📝",
    url_path="meet-setup",
    default=True,
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
    "meet_setup": MEET_SETUP_PAGE,
    "live_timing": LIVE_TIMING_PAGE,
    "results": RESULTS_PAGE,
}

pages = [MEET_SETUP_PAGE, LIVE_TIMING_PAGE, RESULTS_PAGE]

navigation = st.navigation(pages)
navigation.run()
