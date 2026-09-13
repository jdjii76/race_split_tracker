"""Phone-friendly race-day roster editor."""
from __future__ import annotations

import streamlit as st

from split_tracker.formatting import format_distance
from split_tracker.race_day_roster import (
    add_athlete, can_manage_race_day_roster, eligible_destination_races,
    move_athlete, race_accepts_athletes, remove_athlete,
)
from split_tracker.repository import RepositoryError


def _matches(value: str, search: str) -> bool:
    return search.strip().casefold() in value.casefold()


def render() -> None:
    identity = st.session_state.get("app_identity")
    if not can_manage_race_day_roster(identity):
        st.error("Coach or administrator access is required to manage race rosters.")
        return
    repository = st.session_state.get("repository")
    race_id = st.session_state.get("race_day_roster_race_id")
    race = repository.get_race(race_id) if repository and race_id else None
    if race is None:
        st.error("Select a race from the Race Day dashboard first.")
        return
    session = repository.get_active_or_latest_race_session_for_race(race.id)
    roster = repository.list_race_athletes(race.id, include_inactive=True)

    st.title("Race Day Roster")
    st.subheader(race.name)
    details = st.columns(3)
    details[0].metric("Distance", format_distance(race.distance_meters))
    details[1].metric("Status", (session.status if session else race.status).replace("_", " ").title())
    details[2].metric("Entered", len(roster))
    if session and session.status in {"running", "paused"}:
        st.info("This race is live. Late adds are eligible only for future checkpoints; no historical splits are created.")
    if st.button("← Race Day", use_container_width=True):
        st.switch_page(st.session_state.page_registry["meet_dashboard"])

    st.header("Entered athletes")
    roster_search = st.text_input("Search entered athletes", placeholder="Name or bib")
    visible = [a for a in roster if _matches(f"{a.name} {a.bib_number} {a.group} {a.team}", roster_search)]
    if not visible:
        st.caption("No entered athletes match this search.")
    for athlete in visible:
        with st.container(border=True):
            closed = not race_accepts_athletes(repository, race)
            label, move_col, remove_col, dns_col = st.columns([3, 1, 1, 1], vertical_alignment="center")
            label.markdown(f"**{'#' + athlete.bib_number + ' ' if athlete.bib_number else ''}{athlete.name}**")
            if athlete.group or athlete.team:
                label.caption(" • ".join(filter(None, (athlete.group, athlete.team))))
            if move_col.button("Move", key=f"move:{race.id}:{athlete.athlete_id}", disabled=closed, use_container_width=True):
                st.session_state.race_day_move_athlete_id = athlete.athlete_id
            if remove_col.button("Remove", key=f"remove:{race.id}:{athlete.athlete_id}", disabled=closed, use_container_width=True):
                try:
                    remove_athlete(repository, race, athlete.athlete_id, identity)
                    st.success(f"Removed {athlete.name} from {race.name}.")
                    st.rerun()
                except RepositoryError as exc:
                    st.error(str(exc))
                    if "Manage Results" in str(exc) and session:
                        st.session_state.selected_results_session_id = session.id
            if dns_col.button(
                "Mark DNS",
                key=f"dns:{race.id}:{athlete.athlete_id}",
                disabled=not session or session.status not in {"awaiting_review", "completed"},
                use_container_width=True,
            ):
                # DNS is append-only result history, so use the established editor
                # instead of treating it as a roster deletion.
                st.session_state.selected_results_session_id = session.id
                st.session_state.manage_results_open = True
                st.switch_page(st.session_state.page_registry["results"])
            if st.session_state.get("race_day_move_athlete_id") == athlete.athlete_id:
                st.markdown(f"**Move {athlete.name} to:**")
                destinations = eligible_destination_races(repository, race)
                if not destinations:
                    st.caption("No other race in this meet can currently accept athletes.")
                for destination in destinations:
                    status = repository.get_active_or_latest_race_session_for_race(destination.id)
                    note = " · late add to running race" if status and status.status in {"running", "paused"} else ""
                    if st.button(f"{destination.name} — {format_distance(destination.distance_meters)}{note}", key=f"destination:{athlete.athlete_id}:{destination.id}", use_container_width=True):
                        try:
                            move_athlete(repository, race, destination, athlete.athlete_id, identity)
                            st.session_state.race_day_move_athlete_id = None
                            st.success(f"Moved {athlete.name} to {destination.name}.")
                            st.rerun()
                        except RepositoryError as exc:
                            st.error(str(exc))
                if st.button("Cancel", key=f"cancel_move:{athlete.athlete_id}", use_container_width=True):
                    st.session_state.race_day_move_athlete_id = None
                    st.rerun()

    st.header("Add from permanent roster")
    permanent_search = st.text_input("Search permanent roster", placeholder="Name, athlete number, or group")
    groups = sorted({a.team_division for a in repository.list_athletes() if a.team_division})
    selected_group = st.radio("Roster group", ["All", *groups], horizontal=True) if groups else "All"
    entered_ids = {a.athlete_id for a in roster}
    candidates = [
        athlete for athlete in repository.list_athletes(search=permanent_search or None)
        if athlete.id not in entered_ids and (selected_group == "All" or athlete.team_division == selected_group)
    ]
    if not candidates:
        st.caption("No active permanent-roster athletes match these filters.")
    for athlete in candidates:
        name, action = st.columns([4, 1], vertical_alignment="center")
        name.markdown(f"**{'#' + athlete.athlete_number + ' ' if athlete.athlete_number else ''}{athlete.display_name}**")
        name.caption(athlete.team_division or "No roster group")
        if action.button("Add", key=f"add:{race.id}:{athlete.id}", disabled=not race_accepts_athletes(repository, race), use_container_width=True):
            try:
                add_athlete(repository, race, athlete.id, identity)
                st.success(f"Added {athlete.display_name} to {race.name}.")
                st.rerun()
            except RepositoryError as exc:
                st.error(str(exc))
