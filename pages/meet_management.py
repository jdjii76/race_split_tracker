"""Administrative meet and race setup page."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, time, timezone
import streamlit as st
from split_tracker.branding import render_school_header

from split_tracker.formatting import format_distance
from split_tracker.repository import Course, Meet, MeetTemplate, Race, RepositoryError, TemplateRace
from split_tracker.state import cleanup_after_all_timing_delete, cleanup_after_meet_delete, cleanup_after_race_delete, cleanup_after_test_data_delete, load_race_into_setup


def _repo():
    return st.session_state.repository


def _handle_error(action: str, exc: Exception) -> None:
    st.error(f"{action} failed. Your form data was not discarded. {exc}")


def _open_race_in_setup(meet: Meet, race: Race) -> None:
    """Open a race while containing storage failures within the page."""
    try:
        load_race_into_setup(st.session_state, meet, race)
        st.switch_page(st.session_state.page_registry["meet_setup"])
    except RepositoryError as exc:
        _handle_error("Open race setup", exc)


def _dev_cleanup_enabled() -> bool:
    return os.environ.get("RACE_SPLIT_TRACKER_ENABLE_DEV_CLEANUP", "").strip().lower() in {"1", "true", "yes", "on"}


def _storage_notice() -> None:
    result = st.session_state.repository_result
    if result is None:
        return
    if result.error:
        st.error(f"{result.message} {result.error}")
    elif result.is_temporary:
        st.warning("Supabase is not configured. Meet dashboard data is temporary and will reset when this session ends.")
    else:
        st.success("Supabase storage is configured for meet and race setup metadata.")
    st.caption("Phase 1 stores meets, races, race rosters, timing sessions, and split events. Checkpoint definitions and non-selected direct setup data remain session-only.")


def _create_meet_form() -> None:
    st.subheader("Create Meet")
    with st.form("create_meet"):
        name = st.text_input("Meet name", placeholder="Creekside Invitational")
        c1, c2, c3 = st.columns(3)
        meet_date = c1.date_input("Meet date", value=None)
        location = c2.text_input("Location")
        season = c3.text_input("Season", placeholder="2026 XC")
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Create meet", type="primary")
    if submitted:
        if not name.strip():
            st.error("Meet name is required.")
            return
        try:
            meet = _repo().create_meet(Meet(name=name.strip(), meet_date=meet_date, location=location.strip(), season=season.strip(), notes=notes.strip(), status="draft"))
            st.session_state.selected_meet_id = meet.id
            st.session_state.active_meet_id = meet.id
            st.success(f"Created {meet.name}.")
            st.rerun()
        except RepositoryError as exc:
            _handle_error("Create meet", exc)


def _meet_list() -> None:
    st.subheader("Saved Meets")
    meets = _repo().list_meets(include_archived=True)
    seasons = sorted({meet.season for meet in meets if meet.season})
    season_filter = st.selectbox("Filter by season", ["All seasons", *seasons])
    if season_filter != "All seasons":
        meets = [meet for meet in meets if meet.season == season_filter]
    if not meets:
        st.info("No saved meets yet.")
        return
    for meet in meets:
        race_count = len(_repo().list_races_for_meet(meet.id))
        with st.expander(f"{meet.name} • {meet.status} • {race_count} races", expanded=meet.id == st.session_state.selected_meet_id):
            st.write(f"**Date:** {meet.meet_date or '—'}  ")
            st.write(f"**Location:** {meet.location or '—'}  ")
            st.write(f"**Season:** {meet.season or '—'}  ")
            st.write(f"**Status:** {meet.status}  ")
            c1, c2, c3 = st.columns(3)
            if c1.button("Open meet", key=f"open_meet_{meet.id}"):
                st.session_state.selected_meet_id = meet.id
                st.session_state.active_meet_id = meet.id
                st.rerun()
            if c2.button("Archive", key=f"archive_meet_{meet.id}", disabled=meet.status == "archived"):
                try:
                    _repo().archive_meet(meet.id)
                    st.rerun()
                except RepositoryError as exc:
                    _handle_error("Archive meet", exc)
            races = _repo().list_races_for_meet(meet.id)
            typed = c3.text_input("Type meet name to delete", key=f"delete_meet_name_{meet.id}", placeholder=meet.name)
            if c3.button("Delete meet", key=f"delete_meet_{meet.id}", disabled=typed != meet.name):
                try:
                    if _repo().delete_meet(meet.id):
                        cleanup_after_meet_delete(st.session_state, meet.id, [race.id for race in races])
                        st.success(f"Deleted meet {meet.name} and its races, rosters, sessions, and split events.")
                    else:
                        st.error("Meet was not found; nothing was deleted.")
                    st.rerun()
                except RepositoryError as exc:
                    _handle_error("Delete meet", exc)


def _meet_detail() -> None:
    meet_id = st.session_state.selected_meet_id
    meet = _repo().get_meet(meet_id) if meet_id else None
    if meet is None:
        return
    st.header(meet.name)
    with st.form(f"edit_meet_{meet.id}"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Meet name", value=meet.name)
        meet_date = c2.date_input("Meet date", value=meet.meet_date)
        status = c3.selectbox("Status", ["draft", "active", "upcoming", "completed", "archived"], index=["draft", "active", "upcoming", "completed", "archived"].index(meet.status))
        location = st.text_input("Location", value=meet.location)
        season = st.text_input("Season", value=meet.season)
        notes = st.text_area("Notes", value=meet.notes)
        if st.form_submit_button("Save meet details"):
            try:
                _repo().update_meet(replace(meet, name=name.strip(), meet_date=meet_date, location=location.strip(), season=season.strip(), notes=notes.strip(), status=status))
                st.success("Meet updated.")
                st.rerun()
            except RepositoryError as exc:
                _handle_error("Update meet", exc)
    _race_management(meet)


def _race_management(meet: Meet) -> None:
    st.subheader("Races")
    races = _repo().list_races_for_meet(meet.id)
    courses = _repo().list_courses()
    with st.expander("Create a reusable course"):
        with st.form(f"add_course_{meet.id}"):
            cc1, cc2 = st.columns(2)
            course_name = cc1.text_input("Course name")
            course_location = cc2.text_input("Course location")
            course_distance = cc1.number_input("Course distance (meters, optional)", min_value=0.0, value=0.0, step=100.0)
            course_notes = cc2.text_input("Course notes")
            if st.form_submit_button("Create course"):
                try:
                    _repo().create_course(Course(course_name=course_name, location=course_location, distance_meters=course_distance or None, notes=course_notes))
                    st.rerun()
                except RepositoryError as exc: _handle_error("Create course", exc)
    with st.form(f"add_race_{meet.id}"):
        c1, c2, c3, c4 = st.columns(4)
        name = c1.text_input("Race name", placeholder="Boys Varsity")
        category = c2.text_input("Category", placeholder="Varsity")
        distance = c3.number_input("Distance (meters)", min_value=1.0, value=5000.0, step=100.0)
        course_type = c4.selectbox("Course type", ["Cross Country", "Track"])
        course_id = st.selectbox("Course (optional)", [None, *(course.id for course in courses)], format_func=lambda value: "Unknown / not linked" if value is None else next(course.course_name for course in courses if course.id == value))
        scheduled_enabled = st.checkbox("Schedule a race start")
        start_date, start_time = st.columns(2)
        scheduled_date = start_date.date_input(
            "Scheduled start date (UTC)", value=meet.meet_date, disabled=not scheduled_enabled
        )
        scheduled_time = start_time.time_input(
            "Scheduled start time (UTC)", value=time(8, 0), disabled=not scheduled_enabled
        )
        if st.form_submit_button("Add race"):
            if scheduled_enabled and scheduled_date is None:
                st.error("Scheduled start date is required when scheduling a race.")
                return
            scheduled_start = (
                datetime.combine(scheduled_date, scheduled_time, tzinfo=timezone.utc)
                if scheduled_enabled else None
            )
            try:
                _repo().create_race(Race(meet_id=meet.id, name=name.strip(), race_category=category.strip(), scheduled_start=scheduled_start, distance_meters=float(distance), course_type=course_type, course_id=course_id, display_order=len(races)))
                st.rerun()
            except RepositoryError as exc:
                _handle_error("Add race", exc)
    if not races:
        st.info("No races yet.")
        return
    for race in races:
        with st.expander(f"{race.display_order + 1}. {race.name} • {format_distance(race.distance_meters)} • {race.status}"):
            st.write(f"**Category:** {race.race_category or '—'}  ")
            st.write(f"**Scheduled start:** {race.scheduled_start or '—'}  ")
            st.write(f"**Course:** {race.course_type or '—'}  ")
            with st.form(f"edit_race_{race.id}"):
                c1, c2, c3, c4 = st.columns(4)
                race_name = c1.text_input("Race name", value=race.name)
                category = c2.text_input("Category", value=race.race_category)
                distance = c3.number_input("Distance meters", min_value=1.0, value=float(race.distance_meters), step=100.0)
                status = c4.selectbox("Status", ["draft", "ready", "running", "paused", "completed", "archived"], index=["draft", "ready", "running", "paused", "completed", "archived"].index(race.status))
                schedule_race = st.checkbox("Schedule a race start", value=race.scheduled_start is not None, key=f"schedule_{race.id}")
                start_date, start_time = st.columns(2)
                race_start_date = start_date.date_input(
                    "Scheduled start date (UTC)",
                    value=race.scheduled_start.date() if race.scheduled_start else meet.meet_date,
                    disabled=not schedule_race,
                    key=f"start_date_{race.id}",
                )
                race_start_time = start_time.time_input(
                    "Scheduled start time (UTC)",
                    value=race.scheduled_start.time().replace(tzinfo=None) if race.scheduled_start else time(8, 0),
                    disabled=not schedule_race,
                    key=f"start_time_{race.id}",
                )
                order = st.number_input("Display order", min_value=0, value=int(race.display_order), step=1, key=f"order_{race.id}")
                linked_course = st.selectbox("Permanent course", [None, *(course.id for course in courses)], index=[None, *(course.id for course in courses)].index(race.course_id) if race.course_id in {course.id for course in courses} else 0, format_func=lambda value: "Unknown / not linked" if value is None else next(course.course_name for course in courses if course.id == value))
                if st.form_submit_button("Save race"):
                    if schedule_race and race_start_date is None:
                        st.error("Scheduled start date is required when scheduling a race.")
                        return
                    scheduled_start = (
                        datetime.combine(race_start_date, race_start_time, tzinfo=timezone.utc)
                        if schedule_race else None
                    )
                    try:
                        _repo().update_race(replace(race, name=race_name.strip(), race_category=category.strip(), scheduled_start=scheduled_start, distance_meters=float(distance), status=status, course_id=linked_course, display_order=int(order)))
                        st.success("Race updated.")
                        st.rerun()
                    except RepositoryError as exc:
                        _handle_error("Update race", exc)
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("Open in Race Setup", key=f"open_race_{race.id}"):
                _open_race_in_setup(meet, race)
            if c2.button("Duplicate", key=f"duplicate_race_{race.id}"):
                try:
                    _repo().duplicate_race(race.id)
                    st.rerun()
                except RepositoryError as exc:
                    _handle_error("Duplicate race", exc)
            if c3.button("Archive", key=f"archive_race_{race.id}", disabled=race.status == "archived"):
                try:
                    _repo().archive_race(race.id)
                    st.rerun()
                except RepositoryError as exc:
                    _handle_error("Archive race", exc)
            typed = c4.text_input("Type race name to delete", key=f"delete_race_name_{race.id}", placeholder=race.name)
            if c4.button("Delete race", key=f"delete_race_{race.id}", disabled=typed != race.name):
                try:
                    if _repo().delete_race(race.id):
                        cleanup_after_race_delete(st.session_state, race.id)
                        st.success(f"Deleted race {race.name} and its roster, sessions, and split events.")
                    else:
                        st.error("Race was not found; nothing was deleted.")
                    st.rerun()
                except RepositoryError as exc:
                    _handle_error("Delete race", exc)


def _development_cleanup() -> None:
    st.header("Development/Admin Cleanup")
    if not _dev_cleanup_enabled():
        st.info("Set RACE_SPLIT_TRACKER_ENABLE_DEV_CLEANUP=true to enable destructive development cleanup actions.")
        return
    st.error("Destructive development cleanup is enabled. These actions do not delete templates, template races, schema objects, migrations, or Supabase configuration.")
    meets = _repo().list_meets(include_archived=True)
    races = [race for meet in meets for race in _repo().list_races_for_meet(meet.id)]
    timing_sessions = [session for race in races for session in _repo().list_race_sessions_for_race(race.id)]
    roster_count = sum(len(_repo().list_race_athletes(race.id, include_inactive=True)) for race in races)
    split_count = sum(len(_repo().list_all_split_events(session.id)) for session in timing_sessions)
    st.write(
        f"Current removable data: {len(timing_sessions)} timing session(s), {split_count} split event(s), "
        f"{roster_count} roster row(s), {len(meets)} meet(s), and {len(races)} race(s)."
    )
    st.write("Type `DELETE TEST DATA` to enable cleanup buttons.")
    phrase = st.text_input("Confirmation phrase", key="delete_test_data_phrase")
    confirmed = phrase == "DELETE TEST DATA"
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Delete timing sessions + splits", disabled=not confirmed, use_container_width=True):
        try:
            deleted = _repo().delete_all_timing_data()
            st.success("Deleted timing sessions and split events." if deleted else "No timing data found.")
            cleanup_after_all_timing_delete(st.session_state)
            st.rerun()
        except RepositoryError as exc:
            _handle_error("Delete timing data", exc)
    if c2.button("Delete race rosters", disabled=not confirmed, use_container_width=True):
        try:
            deleted = _repo().delete_all_race_rosters()
            st.success("Deleted all race rosters." if deleted else "No race rosters found.")
            st.session_state.race_rosters = {}
            st.session_state.athletes = []
            st.rerun()
        except RepositoryError as exc:
            _handle_error("Delete race rosters", exc)
    if c3.button("Delete meets + races", disabled=not confirmed, use_container_width=True):
        try:
            deleted = _repo().delete_all_application_test_data()
            st.success("Deleted meets, races, rosters, sessions, and splits." if deleted else "No meet/race test data found.")
            cleanup_after_test_data_delete(st.session_state)
            st.rerun()
        except RepositoryError as exc:
            _handle_error("Delete meets and races", exc)
    if c4.button("Delete all app test data", disabled=not confirmed, use_container_width=True):
        try:
            deleted = _repo().delete_all_application_test_data()
            st.success("Deleted all application test data while preserving templates." if deleted else "No application test data found.")
            cleanup_after_test_data_delete(st.session_state)
            st.rerun()
        except RepositoryError as exc:
            _handle_error("Delete app test data", exc)


def _templates() -> None:
    st.header("Templates")
    templates = _repo().list_templates(include_archived=True)
    st.caption("Default XC template: Boys JV, Girls JV, Boys Varsity, Girls Varsity; all default to 5000 meters.")
    with st.form("create_template"):
        name = st.text_input("Template name")
        description = st.text_input("Description")
        season = st.text_input("Season")
        race_names = st.text_area("Template races, one per line", value="Boys JV\nGirls JV\nBoys Varsity\nGirls Varsity")
        if st.form_submit_button("Create template"):
            try:
                template = MeetTemplate(name=name.strip(), description=description.strip(), season=season.strip())
                races = [TemplateRace(template_id=template.id, name=line.strip(), distance_meters=5000.0, display_order=index) for index, line in enumerate(race_names.splitlines()) if line.strip()]
                _repo().create_template(template, races)
                st.rerun()
            except RepositoryError as exc:
                _handle_error("Create template", exc)
    for template in templates:
        races = _repo().list_template_races(template.id)
        with st.expander(f"{template.name} • {template.status} • {len(races)} races"):
            st.write(template.description or "No description")
            st.write(", ".join(race.name for race in races) or "No races")
            with st.form(f"apply_template_{template.id}"):
                meet_name = st.text_input("New meet name", key=f"meet_name_{template.id}")
                meet_date = st.date_input("Meet date", value=None, key=f"meet_date_{template.id}")
                location = st.text_input("Location", key=f"location_{template.id}")
                if st.form_submit_button("Create meet from template", disabled=template.status == "archived"):
                    try:
                        meet, _ = _repo().apply_template_to_meet(template.id, Meet(name=meet_name.strip(), meet_date=meet_date, location=location.strip(), season=template.season))
                        st.session_state.selected_meet_id = meet.id
                        st.session_state.active_meet_id = meet.id
                        st.success("Meet created from template.")
                        st.rerun()
                    except RepositoryError as exc:
                        _handle_error("Apply template", exc)
            c1, c2 = st.columns(2)
            if c1.button("Archive template", key=f"archive_template_{template.id}", disabled=template.status == "archived"):
                try:
                    _repo().archive_template(template.id)
                    st.rerun()
                except RepositoryError as exc:
                    _handle_error("Archive template", exc)
            with c2.form(f"edit_template_{template.id}"):
                new_name = st.text_input("Edit name", value=template.name)
                new_description = st.text_input("Edit description", value=template.description)
                if st.form_submit_button("Save template"):
                    try:
                        _repo().update_template(replace(template, name=new_name.strip(), description=new_description.strip()))
                        st.rerun()
                    except RepositoryError as exc:
                        _handle_error("Update template", exc)


def render() -> None:
    """Render the dashboard."""
    render_school_header(st.session_state.school_profile, "Meets & Races")
    _storage_notice()
    if _repo() is None:
        st.stop()
    tab_meets, tab_templates, tab_admin = st.tabs(["Meets", "Templates", "Development/Admin"])
    with tab_meets:
        _create_meet_form()
        _meet_list()
        _meet_detail()
    with tab_templates:
        _templates()
    with tab_admin:
        _development_cleanup()
