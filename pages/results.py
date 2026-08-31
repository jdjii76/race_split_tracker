"""Results page."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from split_tracker.branding import branded_export_filename, render_school_header

from split_tracker.calculations import generate_checkpoints
from split_tracker.formatting import format_distance, format_duration, parse_time_to_seconds
from split_tracker.repository import RaceRepository, RepositoryError, ResultEvent, canonical_result_events
from split_tracker.results import build_team_summary, filter_results, normalize_manual_checkpoint_times, printable_results_html, reconstruct_results, results_to_frame, session_label, summarize_sessions
from split_tracker.spectator import spectator_url
from split_tracker.session_checkpoints import get_session_checkpoints
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
    profile = st.session_state.school_profile
    st.download_button("Download CSV", data=frame.to_csv(index=False).encode("utf-8"), file_name=branded_export_filename(profile, ["race", "splits"], "csv"), mime="text/csv", use_container_width=True)


def _filter_options(rows: list[dict[str, object]], key: str) -> list[str]:
    values = sorted({str(row.get(key) or "") for row in rows if row.get(key)})
    return ["All", *values]


def _manage_results(repository, session, athletes, checkpoints, rows, result_events, split_events) -> None:
    """Render the narrow post-timing result editor."""
    st.subheader("Manage Results")
    st.caption("Add a missed result or append a correction. Earlier values remain in Result History.")
    current = canonical_result_events(result_events)
    by_id = {str(row["Athlete ID"]): row for row in rows}
    summary_rows = [{"Athlete": athlete.name, "Team/Division": athlete.team or athlete.group or "—",
                     "Status": by_id[athlete.athlete_id]["Status"], "Finish Time": by_id[athlete.athlete_id]["Final Time"],
                     "Source": by_id[athlete.athlete_id]["Source"]} for athlete in athletes]
    st.dataframe(pd.DataFrame(summary_rows), hide_index=True, use_container_width=True)
    athlete = st.selectbox("Athlete", athletes, format_func=lambda item: item.name, key=f"manage_athlete_{session.id}")
    existing = current.get(athlete.athlete_id)
    row = by_id[athlete.athlete_id]
    st.markdown(f"**Recorded Result:** {row['Status']} — {row['Final Time']} ({row['Source']})")
    status = st.selectbox("Result status", ["Finished", "DNF", "DNS"], key=f"manage_status_{session.id}_{athlete.athlete_id}")
    finish_text = st.text_input("New finish time", placeholder="22:15.4", disabled=status != "Finished",
                                key=f"manage_finish_{session.id}_{athlete.athlete_id}")
    source = st.selectbox("Result source", ["Manual", "Official"], key=f"manage_source_{session.id}_{athlete.athlete_id}")
    entered_splits = {}
    with st.expander("Optional checkpoint times"):
        entry_label = st.radio(
            "Checkpoint time format",
            ["Cumulative elapsed times", "Segment durations"],
            horizontal=True,
            key=f"manage_cp_format_{session.id}_{athlete.athlete_id}",
        )
        if entry_label == "Cumulative elapsed times":
            st.caption("Enter elapsed race-clock times. Each entered checkpoint must be later than the preceding one.")
        else:
            st.caption("Enter each segment's duration. Faster later segments are valid; entered durations are added in race order.")
        for checkpoint in checkpoints:
            if not checkpoint.is_finish:
                value = st.text_input(checkpoint.label, key=f"manage_cp_{session.id}_{athlete.athlete_id}_{checkpoint.number}")
                if value.strip(): entered_splits[checkpoint.number] = value
    note = st.text_area("Notes / correction reason", key=f"manage_note_{session.id}_{athlete.athlete_id}")
    is_change = row["Status"] not in {"Unresolved", "DNS"} or existing is not None
    confirmed = st.checkbox("I understand this becomes the active result and the recorded result remains in audit history.",
                            disabled=not is_change, key=f"manage_confirm_{session.id}_{athlete.athlete_id}")
    if st.button("Save Result", type="primary", use_container_width=True, disabled=is_change and not confirmed):
        finish = parse_time_to_seconds(finish_text) if status == "Finished" else None
        parsed_splits = {number: parse_time_to_seconds(value) for number, value in entered_splits.items()}
        if status == "Finished" and finish is None:
            st.error("Enter a positive finish time such as 21:34.6 or 1:02:15.4.")
        elif any(value is None for value in parsed_splits.values()):
            st.error("Each checkpoint time must be a positive duration such as 6:32.")
        else:
            try:
                parsed_splits = normalize_manual_checkpoint_times(
                    parsed_splits,
                    entry_type="cumulative" if entry_label == "Cumulative elapsed times" else "segment",
                    finish_seconds=finish,
                )
                repository.save_post_race_result(ResultEvent(session.id, athlete.athlete_id, status.lower(), source.lower(),
                    finish_seconds=finish, splits=parsed_splits, note=note.strip(), supersedes_id=existing.id if existing else None,
                    created_by=getattr(st.session_state.get("app_identity"), "user_id", "")))
                st.success("Result saved. Final results, history, PRs, and public results now use it.")
                st.rerun()
            except (RepositoryError, ValueError) as exc: st.error(str(exc))
    history = [event for event in result_events if event.athlete_id == athlete.athlete_id]
    if history:
        with st.expander("Result History"):
            for event in reversed(history):
                label = "Active" if existing and event.id == existing.id else "Superseded"
                st.write(f"**{label} {event.source.title()}** — {format_duration(event.finish_seconds) if event.status == 'finished' else event.status.upper()} — {event.created_at:%b %d, %Y %H:%M}")
                if event.note: st.caption(event.note)
            live_finish = next((event for event in split_events if event.athlete_id == athlete.athlete_id and
                                any(cp.is_finish and cp.number == event.checkpoint_number for cp in checkpoints)), None)
            if live_finish:
                st.write(f"**Original live timing event** — {format_duration(live_finish.elapsed_seconds)} — preserved in split-event history")


def render() -> None:
    """Render the results page."""
    profile = st.session_state.school_profile
    render_school_header(profile, f"{profile.program_name} Results")
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
    st.caption(f"**{meet.name}** • **{race.name}**")
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

    selected_session_id = st.session_state.get("selected_results_session_id")
    selected_index = next(
        (index for index, item in enumerate(summaries) if item.session_id == selected_session_id),
        0,
    )
    summary = st.selectbox("Race session", summaries, index=selected_index, format_func=session_label)
    st.session_state.selected_results_session_id = summary.session_id
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", summary.status.replace("_", " ").upper())
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
        checkpoint_result = get_session_checkpoints(repository, session, checkpoints)
        events = repository.list_active_split_events(session.id)
        outcomes = repository.list_race_athlete_outcomes(session.id)
        result_events = repository.list_result_events(session.id)
    except RepositoryError as exc:
        st.error(f"Could not load split events: {exc}")
        return

    if checkpoint_result.source == "legacy_fallback":
        st.warning("This legacy race session has no persisted checkpoint snapshot, so results use the current generated race checkpoints as an isolated fallback.")

    rows = reconstruct_results(meet_name=meet.name, race_name=race.name, session=session, athletes=athletes, checkpoints=checkpoint_result.checkpoints, race_distance_meters=race.distance_meters, events=events, outcomes=outcomes, result_events=result_events)
    if not rows:
        st.info("This session has no roster or split events to reconstruct.")
        return

    reviewing = summary.status == "awaiting_review"
    if reviewing:
        st.warning("RACE STATUS: AWAITING REVIEW — Live capture has stopped. Verify unresolved athletes and times before finalizing.")
        manage, correct, finalize = st.columns(3)
        if manage.button("Manage Results", use_container_width=True):
            st.session_state.manage_results_open = True
        if correct.button("Correct Results", use_container_width=True):
            st.session_state.manage_results_open = True
        if finalize.button("Finalize & Publish Results", type="primary", use_container_width=True):
            try:
                repository.finalize_race_session(session.id)
                st.session_state.results_review_session_id = None
                st.success("Results finalized and published to the parent page.")
                st.rerun()
            except RepositoryError as exc:
                st.error(f"Results could not be finalized: {exc}")
        with st.expander("Manage Results", expanded=bool(st.session_state.get("manage_results_open"))):
            _manage_results(repository, session, athletes, checkpoint_result.checkpoints, rows, result_events, events)
    elif summary.status == "completed":
        st.success("FINAL RESULTS — Published to the parent page and retained in race history.")
        if st.button("Open Coach Analytics", type="primary", use_container_width=True):
            st.session_state.analytics_race_id = race.id
            st.session_state.analytics_session_id = session.id
            st.switch_page(st.session_state.page_registry["coach_analytics"])
        with st.expander("Manage Results", expanded=bool(st.session_state.get("manage_results_open"))):
            _manage_results(repository, session, athletes, checkpoint_result.checkpoints, rows, result_events, events)

    st.subheader("Final Results" if summary.status == "completed" else "Provisional Results")
    final_columns = [column for column in ("Place", "Athlete", "Final Time", "Average Pace", "Split Times", "Status")]
    st.dataframe(results_to_frame(rows)[final_columns], hide_index=True, use_container_width=True)
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
        value = st.selectbox("Status filter", ["All", "Finished", "DNF", "Unresolved", "In Progress", "DNS"])
        status = None if value == "All" else value

    filtered_rows = filter_results(rows, gender=gender, team=team, category=category, status=status)
    frame = results_to_frame(filtered_rows, formatted_for_export=True)
    with st.expander("Detailed results and export", expanded=False):
        st.dataframe(frame, hide_index=True, use_container_width=True)
    st.download_button(
        "Download selected session CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=branded_export_filename(profile, [meet.meet_date.year if meet.meet_date else "", meet.name, race.name, summary.session_id[:8], "Results"], "csv"),
        mime="text/csv",
        use_container_width=True,
    )
    printable = printable_results_html(meet.name, race.name, rows)
    st.download_button(
        "Download Printable Results",
        data=printable.encode("utf-8"),
        file_name=branded_export_filename(profile, [meet.name, race.name, "print-results"], "html"),
        mime="text/html",
        use_container_width=True,
    )

    team_summary = build_team_summary(rows)
    if team_summary:
        st.subheader("Team Summary")
        st.dataframe(pd.DataFrame(team_summary), hide_index=True, use_container_width=True)

    if summary.status == "completed":
        st.subheader("Share Final Results")
        public_url = spectator_url(race.id, session.id)
        st.code(public_url, language=None)
        st.link_button("Open Parent Results Page", public_url, use_container_width=True)

    chartable = pd.DataFrame([row for row in rows if row.get("Status") == "Finished"])
    if not chartable.empty:
        st.subheader("Finish Times")
        st.bar_chart(chartable.set_index("Athlete")[["Finish Time Seconds"]])
