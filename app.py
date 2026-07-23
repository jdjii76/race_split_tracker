"""Streamlit entry point for Race Split Tracker."""

from __future__ import annotations

import streamlit as st

from pages import live_timing, meet_setup, results
from split_tracker.state import initialize_state

st.set_page_config(page_title="Race Split Tracker", page_icon="⏱️", layout="wide")
initialize_state(st.session_state)

pages = [
    st.Page(meet_setup.render, title="Meet Setup", icon="📝"),
    st.Page(live_timing.render, title="Live Timing", icon="⏱️"),
    st.Page(results.render, title="Results", icon="📊"),
]

navigation = st.navigation(pages)
navigation.run()
