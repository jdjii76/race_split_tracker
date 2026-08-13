"""Streamlit entry point for Race Split Tracker."""

from __future__ import annotations

import streamlit as st
from dataclasses import replace

from pages import athlete_profile, athletes, coach_analytics, coach_login, live_timing, meet_dashboard, meet_management, meet_setup, results, school_branding, spectator, team_progress
from split_tracker.auth import current_identity, sign_out
from split_tracker.branding import apply_school_theme, load_school_profile, render_school_sidebar_brand
from split_tracker.branding_service import load_cached_profile
from split_tracker.navigation import resolve_active_meet_id
from split_tracker.repository import create_repository
from split_tracker.state import initialize_persistence_state, initialize_state

school_profile, school_profile_warnings = load_school_profile(secrets=st.secrets)
st.set_page_config(page_title=school_profile.app_title, page_icon="🏃", layout="wide")
initialize_state(st.session_state)
initialize_persistence_state(st.session_state)
st.session_state.school_profile = school_profile

if st.session_state.repository_result is None:
    repository_result = create_repository()
    st.session_state.repository_result = repository_result
    st.session_state.repository = repository_result.repository

stored_school_profile, branding_load_warning = load_cached_profile(st.session_state, st.session_state.repository, school_profile)
st.session_state.school_profile_stored = stored_school_profile
school_profile = stored_school_profile
if st.session_state.repository is not None:
    asset_urls = st.session_state.setdefault("school_branding_asset_urls", {})
    for path in (stored_school_profile.logo_path, stored_school_profile.compact_logo_path):
        if path and path not in asset_urls:
            asset_urls[path] = st.session_state.repository.get_branding_asset_url(path)
    logo_url = asset_urls.get(stored_school_profile.logo_path)
    icon_url = asset_urls.get(stored_school_profile.compact_logo_path)
    school_profile = replace(stored_school_profile, logo_path=logo_url or stored_school_profile.logo_path, compact_logo_path=icon_url or stored_school_profile.compact_logo_path)
st.session_state.school_profile = school_profile
apply_school_theme(school_profile)

repository_result = st.session_state.repository_result
spectator_mode = bool(st.query_params.get("spectator_race") or st.query_params.get("spectator_session"))
auth_client = getattr(st.session_state.repository, "client", None)
identity = current_identity(auth_client) if auth_client is not None and not spectator_mode else None
st.session_state.app_identity = identity
authenticated = bool(identity and identity.is_coach)
if not spectator_mode and authenticated and st.session_state.repository is not None:
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
if not spectator_mode and authenticated:
    with st.sidebar:
        render_school_sidebar_brand(school_profile)
        st.caption(f"Signed in as {identity.email} • {identity.role.title()}")
        if st.button("Sign Out", use_container_width=True):
            sign_out(auth_client)
            st.session_state.app_identity = None
            st.rerun()
        for warning in school_profile_warnings:
            st.caption(f"Branding configuration: {warning}")
        if branding_load_warning:
            st.caption(branding_load_warning)
        if st.session_state.get("branding_flash"):
            st.success(st.session_state.pop("branding_flash"))
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
    title="Race Day",
    icon="🏟️",
    url_path="meet-dashboard",
    default=True,
)
MEET_SETUP_PAGE = st.Page(
    meet_management.render,
    title="Meets & Races",
    icon="📝",
    url_path="meet-setup",
)
ATHLETES_PAGE = st.Page(athletes.render, title="Athletes", icon="🏃", url_path="athletes")
ATHLETE_PROFILE_PAGE = st.Page(athlete_profile.render, title="Athlete Profile", icon="📈", url_path="athlete-profile")
TEAM_PROGRESS_PAGE = st.Page(team_progress.render, title="Team Progress", icon="📊", url_path="team-progress")
COACH_ANALYTICS_PAGE = st.Page(coach_analytics.render, title="Coach Analytics", icon="📋", url_path="coach-analytics")
CONFIGURE_RACE_PAGE = st.Page(
    meet_setup.render,
    title="Race Setup",
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
SCHOOL_BRANDING_PAGE = st.Page(
    school_branding.render,
    title="School & Branding",
    icon="🎨",
    url_path="school-branding",
)
SPECTATOR_PAGE = st.Page(
    spectator.render,
    title="Live Race",
    icon="🏁",
    url_path="live-race",
)
COACH_LOGIN_PAGE = st.Page(
    coach_login.render,
    title="Coach Sign In",
    icon="🔐",
    url_path="coach-sign-in",
)

st.session_state.page_registry = {
    "meet_dashboard": MEET_DASHBOARD_PAGE,
    "meet_setup": CONFIGURE_RACE_PAGE,
    "race_setup": MEET_SETUP_PAGE,
    "live_timing": LIVE_TIMING_PAGE,
    "results": RESULTS_PAGE,
    "school_branding": SCHOOL_BRANDING_PAGE,
    "athletes": ATHLETES_PAGE,
    "athlete_profile": ATHLETE_PROFILE_PAGE,
    "coach_analytics": COACH_ANALYTICS_PAGE,
    "spectator": SPECTATOR_PAGE,
}

race_day_pages = [MEET_DASHBOARD_PAGE, LIVE_TIMING_PAGE, RESULTS_PAGE]
settings_pages = []
if identity and identity.is_admin:
    race_day_pages.insert(1, ATHLETES_PAGE)
    race_day_pages.insert(2, TEAM_PROGRESS_PAGE)
    race_day_pages.insert(3, ATHLETE_PROFILE_PAGE)
    race_day_pages.insert(4, COACH_ANALYTICS_PAGE)
    settings_pages.append(SCHOOL_BRANDING_PAGE)
pages = {
    "Race Day": race_day_pages,
    "Setup": [MEET_SETUP_PAGE, CONFIGURE_RACE_PAGE],
}
if settings_pages:
    pages["Settings"] = settings_pages

if spectator_mode:
    navigation = st.navigation([SPECTATOR_PAGE], position="hidden")
elif not authenticated:
    navigation = st.navigation([COACH_LOGIN_PAGE], position="hidden")
else:
    navigation = st.navigation(pages)
navigation.run()
