"""Permanent school athlete roster administration."""
from __future__ import annotations
from dataclasses import replace
from datetime import date
import pandas as pd
import streamlit as st
from split_tracker.athletes import grade_from_graduation_year
from split_tracker.branding import render_school_header
from split_tracker.models import PermanentAthlete
from split_tracker.repository import RepositoryError

STATUSES = ["active", "inactive", "injured", "graduated"]


def _year_end() -> int:
    today = date.today()
    return today.year + 1 if today.month >= 7 else today.year


def _save_new() -> None:
    with st.form("add_permanent_athlete", clear_on_submit=True):
        st.subheader("Add Athlete")
        c1, c2, c3 = st.columns(3)
        first = c1.text_input("First name")
        last = c2.text_input("Last name")
        preferred = c3.text_input("Preferred name")
        graduation = c1.number_input("Graduation year", min_value=2000, max_value=2100, value=None, step=1)
        gender = c2.text_input("Gender")
        division = c3.text_input("Team division")
        number = c1.text_input("Athlete number")
        status = c2.selectbox("Status", STATUSES)
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Add Athlete", type="primary")
    if submitted:
        try:
            saved = st.session_state.repository.create_athlete(PermanentAthlete(
                first_name=first, last_name=last, preferred_name=preferred,
                graduation_year=int(graduation) if graduation else None, gender=gender,
                team_division=division, athlete_number=number, status=status, notes=notes,
            ))
            st.session_state.athlete_roster_flash = f"Added {saved.display_name}."
            st.rerun()
        except (RepositoryError, ValueError) as exc:
            st.error(str(exc))


def render() -> None:
    profile = st.session_state.school_profile
    title = f"{profile.short_name} Athlete Roster" if profile.short_name else "Athlete Roster"
    render_school_header(profile, title)
    repository = st.session_state.repository
    if repository is None:
        st.error("The permanent roster is unavailable. Race timing remains available for existing race rosters.")
        return
    if st.session_state.get("athlete_roster_flash"):
        st.success(st.session_state.pop("athlete_roster_flash"))
    _save_new()
    st.subheader("School Roster")
    c1, c2, c3, c4 = st.columns(4)
    status_filter = c1.selectbox("Status", ["active", "All", "inactive", "injured", "graduated"], format_func=str.title)
    search = c2.text_input("Search name or number")
    try:
        all_athletes = repository.list_athletes(search=search or None)
    except RepositoryError as exc:
        st.error(str(exc)); return
    years = sorted({item.graduation_year for item in all_athletes if item.graduation_year})
    year = c3.selectbox("Graduation year", ["All", *years])
    divisions = sorted({item.team_division for item in all_athletes if item.team_division})
    division = c4.selectbox("Team division", ["All", *divisions])
    filtered = [item for item in all_athletes if (status_filter == "All" or item.status == status_filter) and (year == "All" or item.graduation_year == year) and (division == "All" or item.team_division == division)]
    frame = pd.DataFrame([{
        "Name": item.display_name, "Preferred name": item.preferred_name or "—",
        "Graduation year": item.graduation_year or "—", "Grade": grade_from_graduation_year(item.graduation_year, _year_end()),
        "Gender / division": " / ".join(value for value in (item.gender, item.team_division) if value) or "—",
        "Status": item.status.title(), "Athlete number": item.athlete_number or "—",
    } for item in filtered])
    if frame.empty: st.info("No athletes match these filters.")
    else: st.dataframe(frame, hide_index=True, use_container_width=True)
    st.caption("Status changes do not remove athletes from historical races or alter race-time name snapshots.")
    for athlete in filtered:
        with st.expander(f"Edit {athlete.display_name} • {athlete.status}"):
            with st.form(f"edit_permanent_athlete_{athlete.id}"):
                c1, c2, c3 = st.columns(3)
                first = c1.text_input("First name", athlete.first_name)
                last = c2.text_input("Last name", athlete.last_name)
                preferred = c3.text_input("Preferred name", athlete.preferred_name)
                graduation = c1.number_input("Graduation year", 2000, 2100, athlete.graduation_year, step=1)
                gender = c2.text_input("Gender", athlete.gender)
                division = c3.text_input("Team division", athlete.team_division)
                number = c1.text_input("Athlete number", athlete.athlete_number)
                status = c2.selectbox("Roster status", STATUSES, index=STATUSES.index(athlete.status))
                notes = st.text_area("Notes", athlete.notes)
                submitted = st.form_submit_button("Save Athlete", type="primary")
            if submitted:
                try:
                    saved = repository.update_athlete(replace(athlete, first_name=first, last_name=last, preferred_name=preferred, graduation_year=int(graduation) if graduation else None, gender=gender, team_division=division, athlete_number=number, status=status, notes=notes))
                    st.session_state.athlete_roster_flash = f"Updated {saved.display_name}; stable athlete ID preserved."
                    st.rerun()
                except (RepositoryError, ValueError) as exc: st.error(str(exc))
