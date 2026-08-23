"""Compact Supabase Auth sign-in page for coaches, administrators, and timers."""
from __future__ import annotations

import streamlit as st

from split_tracker.auth import AuthenticationError, sign_in
from split_tracker.branding import render_school_header


def render() -> None:
    profile = st.session_state.school_profile
    render_school_header(profile, "Sign In", subtitle="Coaches, administrators, and race-day timers")
    repository = st.session_state.get("repository")
    client = getattr(repository, "client", None)
    if client is None:
        st.error("Sign-in requires a configured Supabase connection.")
        return
    with st.form("coach_sign_in"):
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)
    if submitted:
        try:
            st.session_state.app_identity = sign_in(client, email, password)
            st.rerun()
        except AuthenticationError as exc:
            st.error(str(exc))
