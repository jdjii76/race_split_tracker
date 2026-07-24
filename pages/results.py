"""Results page."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from split_tracker.calculations import generate_checkpoints
from split_tracker.formatting import format_distance, format_duration
from split_tracker.repository import RaceRepository, RepositoryError
from split_tracker.results import filter_results, reconstruct_results, results_to_frame, session_label, summarize_sessions
from split_tracker.state import cleanup_after_session_delete


def _repo() -> RaceRepository | None:
    return st.session_state.get("repository")


def _selected_option(label: str, options, *, format_func, current_id: str | None = None):
    if not options:
        return None
    index = 0
    if current_id:
        for option_index, option in enumerate(options):
            if option.id == current_id:
                index = option_index
                break
    return st.selectbox(label, options, index=index, format_func=format_func)


def _race_checkpoints(race):
    return generate_checkpoints(
        race_distance_meters=race.distance_meters,
        mode=race.checkpoint_mode or "Standard laps",
        interval_meters=400.0 if race.course_type == "Track" else 1609.344,
    )


def _legacy_results() -> None:
    rows = []
    for split in sorted(st.session_state.splits, key=lambda item: item.sequence):
        rows.append(
            {
                "Sequence": split.sequence,
                "Athlete": split.athlete_name,
                "Bib": split.bib_number,
                "Checkpoint": split.checkpoint_number,
                "Distance": split.checkpoint_distance_meters,
                "Cumulative Time": format_duration(split.cumulative_time_seconds),
                "Segment Split": format_duration(split.segment_split_seconds),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        st.info("No saved sessions or local splits are available yet.")
        return
    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.download_button("Download CSV", data=frame.to_csv(index=False).encode("utf-8"), file_name="race_splits.csv", mime="text/csv", use_container_width=True)


def _filter_options(rows: list[dict[str, object]], key: str) -> list[str]:
    values = sorted({str(row.get(key) or "") for row in rows if row.get(key)})
    return ["All", *values]


def render() -> None:
    """Render the results page."""
    st.title("Results")
    repository = _repo()
    if repository is None:
        st.warning("Persistent storage is unavailable. Showing only local session-state splits.")
        _legacy_results()
        return

    try:
        meets = repository.list_meets(include_archived=True)
    except RepositoryError as exc:
        st.error(f"Could not load meets: {exc}")
        return
    if not meets:
        st.info("No saved meets are available yet.")
        return

    meet = _selected_option("Meet", meets, current_id=st.session_state.get("selected_meet_id"), format_func=lambda item: f"{item.name} • {item.meet_date or 'no date'}")
    if meet is None:
        return
    st.session_state.selected_meet_id = meet.id

    try:
        races = repository.list_races_for_meet(meet.id)
    except RepositoryError as exc:
        st.error(f"Could not load races: {exc}")
        return
    if not races:
        st.info("This meet does not have saved races yet.")
        return

    race = _selected_option("Race", races, current_id=st.session_state.get("selected_race_id"), format_func=lambda item: f"{item.name} • {format_distance(item.distance_meters)} • {item.status}")
    if race is None:
        return
    st.session_state.selected_race_id = race.id
    checkpoints = _race_checkpoints(race)

    try:
        athletes = repository.list_race_athletes(race.id, include_inactive=True)
        summaries = summarize_sessions(repository, race_id=race.id, athletes=athletes, checkpoints=checkpoints, race_distance_meters=race.distance_meters)
    except RepositoryError as exc:
        st.error(f"Could not load race history: {exc}")
        return

    if not summaries:
        st.info("No timing sessions exist for this race yet.")
        return

    summary = st.selectbox("Race session", summaries, format_func=session_label)
    st.session_state.selected_results_session_id = summary.session_id
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", summary.status)
    c2.metric("Duration", format_duration(summary.duration_seconds))
    c3.metric("Active splits", summary.active_split_count)
    c4.metric("Finishers", summary.finished_athlete_count)
    st.caption(f"Started: {summary.started_at or '—'} • Ended: {summary.ended_at or '—'}")
    if summary.status == "completed":
        st.info("Completed sessions open read-only here. Use Live Timing only if you intentionally need to resume or correct history; split-event history is preserved with soft deletes.")

    with st.expander("Delete selected race session"):
        st.warning(f"This will delete race session {summary.session_id} and its split events. It will not delete the race or roster.")
        typed = st.text_input("Type DELETE SESSION to confirm", key=f"delete_session_phrase_{summary.session_id}")
        if st.button("Delete race session", key=f"delete_session_{summary.session_id}", disabled=typed != "DELETE SESSION", use_container_width=True):
            try:
                if repository.delete_race_session(summary.session_id):
                    cleanup_after_session_delete(st.session_state, summary.session_id)
                    st.success("Race session and split events deleted.")
                else:
                    st.error("Race session was not found; nothing was deleted.")
                st.rerun()
            except RepositoryError as exc:
                st.error(f"Could not delete race session: {exc}")

    try:
        session = repository.get_race_session(summary.session_id)
        if session is None:
            st.error("Selected race session could not be found.")
            return
        events = repository.list_active_split_events(session.id)
    except RepositoryError as exc:
        st.error(f"Could not load split events: {exc}")
        return

    rows = reconstruct_results(meet_name=meet.name, race_name=race.name, session=session, athletes=athletes, checkpoints=checkpoints, race_distance_meters=race.distance_meters, events=events)
    if not rows:
        st.info("This session has no roster or split events to reconstruct.")
        return

    st.subheader("Reconstructed Results")
    scope = st.radio("Result scope", ["Overall", "Gender", "Team", "Group/category", "Status"], horizontal=True)
    gender = team = category = status = None
    if scope == "Gender":
        value = st.selectbox("Gender filter", _filter_options(rows, "Gender"))
        gender = None if value == "All" else value
    elif scope == "Team":
        value = st.selectbox("Team filter", _filter_options(rows, "Team"))
        team = None if value == "All" else value
    elif scope == "Group/category":
        value = st.selectbox("Group/category filter", _filter_options(rows, "Category/Group"))
        category = None if value == "All" else value
    elif scope == "Status":
        value = st.selectbox("Status filter", ["All", "Finished", "In Progress", "DNF", "DNS"])
        status = None if value == "All" else value

    filtered_rows = filter_results(rows, gender=gender, team=team, category=category, status=status)
    frame = results_to_frame(filtered_rows, formatted_for_export=True)
    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.download_button(
        "Download selected session CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=f"{meet.name}_{race.name}_{summary.session_id[:8]}_results.csv".replace(" ", "_"),
        mime="text/csv",
        use_container_width=True,
    )

    chartable = pd.DataFrame([row for row in rows if row.get("Status") == "Finished"])
    if not chartable.empty:
        st.subheader("Finish Times")
        st.bar_chart(chartable.set_index("Athlete")[["Finish Time Seconds"]])
