"""Permanent school athlete roster administration."""
from __future__ import annotations
from dataclasses import replace
from datetime import date
import pandas as pd
import streamlit as st
from split_tracker.auth import AuthenticationError, require_admin
from split_tracker.athletes import grade_from_graduation_year
from split_tracker.athlete_import import csv_template_bytes, import_athlete_rows, parse_athlete_csv
from split_tracker.branding import render_school_header
from split_tracker.models import PermanentAthlete
from split_tracker.repository import RepositoryError

STATUSES = ["active", "inactive", "injured", "graduated"]


def _run_roster_action(repository, athlete, action: str) -> None:
    try:
        if action == "archive":
            repository.archive_athlete(athlete.id)
            message = f"Archived {athlete.display_name}. Race history was preserved."
        elif action == "restore":
            repository.restore_athlete(athlete.id)
            message = f"Restored {athlete.display_name} to the active roster."
        else:
            repository.delete_unused_athlete(athlete.id)
            message = f"Deleted {athlete.display_name} permanently."
        st.session_state.pop("athlete_pending_action", None)
        st.session_state.athlete_roster_flash = message
        st.rerun()
    except RepositoryError as exc:
        st.error(str(exc))


def _confirmation(repository, athlete, action: str) -> None:
    if action == "archive":
        st.warning(f"**Archive {athlete.display_name}?**")
        st.write(
            f"{athlete.preferred_name or athlete.first_name} will no longer appear in the normal active roster or new-race selection. "
            "Existing race results and history will remain unchanged."
        )
        label = "Archive Athlete"
    else:
        st.warning(f"**Delete {athlete.display_name} permanently?**")
        st.write("This athlete has no race history. This action cannot be undone.")
        label = "Delete Permanently"
    cancel, confirm = st.columns(2)
    if cancel.button("Cancel", key=f"cancel_{action}_{athlete.id}", use_container_width=True):
        st.session_state.pop("athlete_pending_action", None)
        st.rerun()
    if confirm.button(label, key=f"confirm_{action}_{athlete.id}", use_container_width=True):
        _run_roster_action(repository, athlete, action)


def _import_roster(repository) -> None:
    with st.expander("Import Athlete Roster"):
        st.write("Upload once to populate the permanent school roster. Review every row before confirming; this does not select athletes for a race.")
        st.download_button(
            "Download CSV Template", csv_template_bytes(),
            file_name="KMHS_permanent_athlete_roster_template.csv", mime="text/csv",
            use_container_width=True,
        )
        uploaded = st.file_uploader("Upload permanent athlete roster CSV", type=["csv"], key="permanent_roster_csv")
        if uploaded is None:
            st.caption("Required columns: first_name and last_name. Use the template for all supported optional fields.")
            return
        try:
            existing = repository.list_athletes()
            rows = parse_athlete_csv(uploaded.getvalue(), existing)
        except RepositoryError as exc:
            st.error(f"The existing roster could not be checked: {exc}")
            return
        preview = pd.DataFrame([{
            "CSV row": row.row_number,
            "Name": row.athlete.display_name if row.athlete else "—",
            "Graduation year": row.athlete.graduation_year if row.athlete else "—",
            "Gender": row.athlete.gender if row.athlete else "—",
            "Division": row.athlete.team_division if row.athlete else "—",
            "Athlete number": row.athlete.athlete_number if row.athlete else "—",
            "Status": row.athlete.status if row.athlete else "—",
            "Validation": "; ".join(row.errors) or "Valid",
            "Duplicate review": row.duplicate_reason or "New athlete",
        } for row in rows])
        st.subheader("CSV Preview")
        st.dataframe(preview, hide_index=True, use_container_width=True)
        invalid_count = sum(bool(row.errors) for row in rows)
        duplicate_count = sum(bool(row.duplicate_athlete_id) for row in rows)
        if invalid_count:
            st.error(f"{invalid_count} row(s) are invalid and will not be imported. Correct the CSV and upload it again for a clean import.")
        else:
            st.success(f"All {len(rows)} row(s) passed validation.")
        if duplicate_count:
            st.warning(f"{duplicate_count} possible duplicate(s) require a policy choice. Same names are allowed; review carefully before updating.")
        labels = {
            "Skip possible duplicates": "skip",
            "Update matched permanent athletes": "update",
            "Create new athletes anyway": "create",
        }
        choice = st.radio("Duplicate behavior", list(labels), key="permanent_import_duplicate_policy")
        confirm = st.checkbox("I reviewed the preview and confirm this permanent-roster import.", key="confirm_permanent_import")
        if st.button("Import Permanent Athletes", type="primary", disabled=not confirm or invalid_count > 0, use_container_width=True):
            summary = import_athlete_rows(repository, rows, labels[choice])
            st.session_state.athlete_import_summary = summary
            st.rerun()


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
    try:
        require_admin(st.session_state.get("app_identity"))
    except AuthenticationError as exc:
        st.error(str(exc))
        return
    profile = st.session_state.school_profile
    title = f"{profile.short_name} Athlete Roster" if profile.short_name else "Athlete Roster"
    render_school_header(profile, title)
    repository = st.session_state.repository
    if repository is None:
        st.error("The permanent roster is unavailable. Race timing remains available for existing race rosters.")
        return
    if st.session_state.get("athlete_roster_flash"):
        st.success(st.session_state.pop("athlete_roster_flash"))
    if st.session_state.get("athlete_import_summary"):
        summary = st.session_state.pop("athlete_import_summary")
        st.success(f"Import complete: {summary.created} created, {summary.updated} updated, {summary.skipped} skipped, {summary.failed} failed.")
    _import_roster(repository)
    _save_new()
    st.subheader("School Roster")
    c1, c2, c3, c4 = st.columns(4)
    status_filter = c1.selectbox("Status", ["active", "archived", "All", "inactive", "injured", "graduated"], format_func=str.title)
    search = c2.text_input("Search name or number")
    try:
        all_athletes = repository.list_athletes(search=search or None, include_archived=True)
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
    st.caption("Archive preserves athlete UUIDs, race rosters, split events, results, and race-time name snapshots.")
    for athlete in filtered:
        details = [athlete.display_name]
        if athlete.athlete_number:
            details.append(f"#{athlete.athlete_number}")
        if athlete.graduation_year:
            details.append(str(athlete.graduation_year))
        details.append(athlete.status.title())
        with st.container(border=True):
            st.markdown(f"**{' • '.join(details)}**")
            if st.button("View Profile", key=f"profile_{athlete.id}", use_container_width=True):
                st.session_state.profile_athlete_id = athlete.id
                st.switch_page(st.session_state.page_registry["athlete_profile"])
            if athlete.status == "archived":
                if st.button("Restore", key=f"restore_{athlete.id}"):
                    _run_roster_action(repository, athlete, "restore")
                continue
            try:
                has_history = repository.athlete_has_race_history(athlete.id)
            except RepositoryError as exc:
                st.error(f"Actions unavailable because race history could not be checked: {exc}")
                has_history = None
            actions = st.columns(2)
            action = "archive" if has_history else "delete"
            label = "Archive" if has_history else "Delete"
            if has_history is not None and actions[1].button(label, key=f"request_{action}_{athlete.id}"):
                st.session_state.athlete_pending_action = (action, athlete.id)
                st.rerun()
            if st.session_state.get("athlete_pending_action") == (action, athlete.id):
                _confirmation(repository, athlete, action)
            with st.expander("Edit"):
                _edit_athlete(repository, athlete)


def _edit_athlete(repository, athlete) -> None:
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
        except (RepositoryError, ValueError) as exc:
            st.error(str(exc))
