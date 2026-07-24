"""Meet Dashboard page for Phase 1 persistence."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd
import streamlit as st

from split_tracker.formatting import format_distance
from split_tracker.repository import Meet, MeetTemplate, Race, RepositoryError, TemplateRace
from split_tracker.state import load_race_into_setup


def _repo():
    return st.session_state.repository


def _handle_error(action: str, exc: Exception) -> None:
    st.error(f"{action} failed. Your form data was not discarded. {exc}")


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
    st.caption("Phase 1 stores meet/race/template setup only. Rosters, checkpoints, splits, and live results remain session-only and will be added in later phases.")


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
                st.rerun()
            if c2.button("Archive", key=f"archive_meet_{meet.id}", disabled=meet.status == "archived"):
                try:
                    _repo().archive_meet(meet.id)
                    st.rerun()
                except RepositoryError as exc:
                    _handle_error("Archive meet", exc)
            confirm = c3.checkbox("Confirm delete", key=f"delete_meet_confirm_{meet.id}")
            if c3.button("Delete draft", key=f"delete_meet_{meet.id}", disabled=meet.status != "draft" or not confirm):
                try:
                    if not _repo().delete_draft_meet(meet.id):
                        st.error("Only draft meets can be deleted. Archive this meet instead.")
                    st.rerun()
                except RepositoryError as exc:
                    _handle_error("Delete draft meet", exc)


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
    with st.form(f"add_race_{meet.id}"):
        c1, c2, c3, c4 = st.columns(4)
        name = c1.text_input("Race name", placeholder="Boys Varsity")
        category = c2.text_input("Category", placeholder="Varsity")
        distance = c3.number_input("Distance (meters)", min_value=1.0, value=5000.0, step=100.0)
        course_type = c4.selectbox("Course type", ["Cross Country", "Track"])
        if st.form_submit_button("Add race"):
            try:
                _repo().create_race(Race(meet_id=meet.id, name=name.strip(), race_category=category.strip(), distance_meters=float(distance), course_type=course_type, display_order=len(races)))
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
                order = st.number_input("Display order", min_value=0, value=int(race.display_order), step=1, key=f"order_{race.id}")
                if st.form_submit_button("Save race"):
                    try:
                        _repo().update_race(replace(race, name=race_name.strip(), race_category=category.strip(), distance_meters=float(distance), status=status, display_order=int(order)))
                        st.success("Race updated.")
                        st.rerun()
                    except RepositoryError as exc:
                        _handle_error("Update race", exc)
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("Open in Meet Setup", key=f"open_race_{race.id}"):
                load_race_into_setup(st.session_state, meet, race)
                st.switch_page(st.session_state.page_registry["meet_setup"])
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
            confirm = c4.checkbox("Confirm delete", key=f"delete_race_confirm_{race.id}")
            if c4.button("Delete draft", key=f"delete_race_{race.id}", disabled=race.status != "draft" or not confirm):
                try:
                    if not _repo().delete_draft_race(race.id):
                        st.error("Only draft races can be deleted. Archive this race instead.")
                    st.rerun()
                except RepositoryError as exc:
                    _handle_error("Delete race", exc)


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
    st.title("Meet Dashboard")
    _storage_notice()
    if _repo() is None:
        st.stop()
    tab_meets, tab_templates = st.tabs(["Meets", "Templates"])
    with tab_meets:
        _create_meet_form()
        _meet_list()
        _meet_detail()
    with tab_templates:
        _templates()
