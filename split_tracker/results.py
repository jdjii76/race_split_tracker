"""Pure helpers for race history and reconstructed results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import pandas as pd

from split_tracker.calculations import athlete_finished
from split_tracker.formatting import format_duration, format_pace
from split_tracker.models import Athlete, Checkpoint, SplitRecord
from split_tracker.repository import RaceAthleteOutcome, RaceRepository, RaceSession, SplitEvent
from split_tracker.session_checkpoints import get_session_checkpoints
from split_tracker.timing_persistence import persisted_elapsed_seconds, rebuild_splits_from_events


@dataclass(frozen=True)
class SessionSummary:
    """Display summary for one persisted race timing session."""

    session_id: str
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: float
    active_split_count: int
    finished_athlete_count: int


RESULT_STATUSES = ("Finished", "In Progress", "DNF", "DNS")


def session_label(summary: SessionSummary) -> str:
    """Return a safe human-readable label for session selection."""
    started = summary.started_at.isoformat(timespec="seconds") if summary.started_at else "not started"
    return f"{started} • {summary.status} • {format_duration(summary.duration_seconds)} • {summary.active_split_count} splits"


def summarize_sessions(
    repository: RaceRepository,
    *,
    race_id: str,
    athletes: list[Athlete],
    checkpoints: list[Checkpoint],
    race_distance_meters: float,
) -> list[SessionSummary]:
    """List timing sessions for one race with split and finisher counts."""
    summaries: list[SessionSummary] = []
    for session in repository.list_race_sessions_for_race(race_id):
        events = repository.list_active_split_events(session.id)
        checkpoint_result = get_session_checkpoints(repository, session, checkpoints)
        session_checkpoints = checkpoint_result.checkpoints
        splits = rebuild_splits_from_events(events=events, athletes=athletes, config=_config_stub(session_checkpoints, race_distance_meters))
        finished = _finished_athlete_count(splits, session_checkpoints)
        summaries.append(
            SessionSummary(
                session_id=session.id,
                status=session.status,
                started_at=session.started_at,
                ended_at=session.ended_at,
                duration_seconds=persisted_elapsed_seconds(session),
                active_split_count=len(events),
                finished_athlete_count=finished,
            )
        )
    return summaries


def reconstruct_results(
    *,
    meet_name: str,
    race_name: str,
    session: RaceSession,
    athletes: list[Athlete],
    checkpoints: list[Checkpoint],
    race_distance_meters: float,
    events: list[SplitEvent],
    outcomes: list[RaceAthleteOutcome] | None = None,
) -> list[dict[str, object]]:
    """Reconstruct result rows from roster, checkpoints, and active split events."""
    inactive = {event.target_event_id for event in events if event.event_type == "split_voided" and event.target_event_id}
    active_events = [event for event in events if not event.is_deleted and event.event_type != "split_voided" and event.id not in inactive]
    roster = _athletes_with_event_fallbacks(athletes, active_events)
    config = _config_stub(checkpoints, race_distance_meters)
    splits = rebuild_splits_from_events(events=active_events, athletes=roster, config=config)
    splits_by_athlete: dict[str, list[SplitRecord]] = {}
    outcome_by_athlete = {item.athlete_id: item.status for item in (outcomes or [])}
    for split in splits:
        splits_by_athlete.setdefault(split.athlete_id, []).append(split)

    rows = []
    for athlete in sorted(roster, key=lambda item: (item.display_order, item.name, item.athlete_id)):
        athlete_splits = sorted(splits_by_athlete.get(athlete.athlete_id, []), key=lambda split: split.checkpoint_number)
        finish_split = next((split for split in reversed(athlete_splits) if split.is_finish), None)
        latest_split = athlete_splits[-1] if athlete_splits else None
        status = _athlete_status(session.status, athlete_splits, checkpoints, outcome_by_athlete.get(athlete.athlete_id))
        row: dict[str, object] = {
            "Meet": meet_name,
            "Race": race_name,
            "Session ID": session.id,
            "Athlete": athlete.name,
            "Bib": athlete.bib_number,
            "Athlete ID": athlete.athlete_id,
            "Gender": athlete.gender,
            "Grade": athlete.grade,
            "Team": athlete.team,
            "Category/Group": athlete.group,
            "Active": athlete.active,
            "Finish Time Seconds": finish_split.cumulative_time_seconds if finish_split else None,
            "Elapsed Seconds": finish_split.cumulative_time_seconds if finish_split else None,
            "Finish Time": format_duration(finish_split.cumulative_time_seconds if finish_split else None),
            "Final Time": format_duration(finish_split.cumulative_time_seconds if finish_split else None),
            "Average Pace": format_pace(finish_split.average_pace_seconds_per_mile if finish_split else None),
            "Overall Place": None,
            "Gender Place": None,
            "Category Place": None,
            "Status": status,
            "Race Status": status,
            "Place": None,
            "_Finish Event Order": finish_split.sequence if finish_split else None,
        }
        for checkpoint in checkpoints:
            matching = next((split for split in athlete_splits if split.checkpoint_number == checkpoint.number), None)
            row[f"{checkpoint.label} Split"] = format_duration(matching.segment_split_seconds if matching else None)
            row[f"{checkpoint.label} Cumulative"] = format_duration(matching.cumulative_time_seconds if matching else None)
        if latest_split and not finish_split:
            row["Latest Checkpoint"] = latest_split.checkpoint_label
        else:
            row["Latest Checkpoint"] = finish_split.checkpoint_label if finish_split else "—"
        rows.append(row)

    _assign_places(rows, "Overall Place")
    for row in rows:
        row["Place"] = row["Overall Place"] if row["Status"] == "Finished" else "—"
        row["Split Times"] = " / ".join(str(row[f"{checkpoint.label} Cumulative"]) for checkpoint in checkpoints)
    _assign_group_places(rows, "Gender", "Gender Place")
    _assign_group_places(rows, "Category/Group", "Category Place")
    return sorted(rows, key=_result_sort_key)


def results_to_frame(rows: list[dict[str, object]], *, formatted_for_export: bool = False) -> pd.DataFrame:
    """Return a stable results DataFrame for display or CSV export."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    if formatted_for_export and "Finish Time Seconds" in frame.columns:
        frame = frame.drop(columns=["Finish Time Seconds", "_Finish Event Order"], errors="ignore")
    return frame


def build_team_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Summarize finishers and scoring places for each named team."""
    teams: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        team = str(row.get("Team") or "").strip()
        if team:
            teams.setdefault(team, []).append(row)
    summary = []
    for team, team_rows in teams.items():
        finishers = [row for row in team_rows if row.get("Status") == "Finished"]
        scoring = finishers[:5]
        summary.append({
            "Team": team,
            "Finishers": len(finishers),
            "DNF": sum(row.get("Status") == "DNF" for row in team_rows),
            "Top 5 Score": sum(int(row["Place"]) for row in scoring) if len(scoring) == 5 else "—",
            "First Finisher": finishers[0].get("Athlete", "—") if finishers else "—",
        })
    return sorted(summary, key=lambda row: (row["Top 5 Score"] == "—", row["Top 5 Score"] if row["Top 5 Score"] != "—" else 0, row["Team"]))


def printable_results_html(meet_name: str, race_name: str, rows: list[dict[str, object]]) -> str:
    """Build a standalone printable results document without internal IDs."""
    from html import escape

    body = "".join(
        f"<tr><td>{escape(str(row.get('Place', '—')))}</td><td>{escape(str(row.get('Athlete', '')))}</td>"
        f"<td>{escape(str(row.get('Final Time', '—')))}</td><td>{escape(str(row.get('Average Pace', '—')))}</td>"
        f"<td>{escape(str(row.get('Split Times', '—')))}</td><td>{escape(str(row.get('Status', '')))}</td></tr>"
        for row in rows
    )
    return f"""<!doctype html><html><head><meta charset=\"utf-8\"><title>{escape(race_name)} Results</title>
<style>body{{font-family:Arial,sans-serif;margin:2rem}}table{{border-collapse:collapse;width:100%}}th,td{{padding:.5rem;border-bottom:1px solid #bbb;text-align:left}}@media print{{button{{display:none}}}}</style></head>
<body><button onclick=\"window.print()\">Print</button><h1>{escape(meet_name)}</h1><h2>{escape(race_name)} — Results</h2>
<table><thead><tr><th>Place</th><th>Athlete</th><th>Finish</th><th>Average pace</th><th>Splits</th><th>Status</th></tr></thead><tbody>{body}</tbody></table></body></html>"""


def filter_results(
    rows: list[dict[str, object]],
    *,
    gender: str | None = None,
    team: str | None = None,
    category: str | None = None,
    status: str | None = None,
) -> list[dict[str, object]]:
    """Apply optional result-table filters."""
    filtered = rows
    if gender:
        filtered = [row for row in filtered if row.get("Gender") == gender]
    if team:
        filtered = [row for row in filtered if row.get("Team") == team]
    if category:
        filtered = [row for row in filtered if row.get("Category/Group") == category]
    if status:
        filtered = [row for row in filtered if row.get("Status") == status]
    return filtered


def _athlete_status(session_status: str, athlete_splits: list[SplitRecord], checkpoints: list[Checkpoint], outcome_status: str | None = None) -> str:
    if athlete_finished(athlete_splits, checkpoints):
        return "Finished"
    if outcome_status == "dnf":
        return "DNF"
    if session_status == "completed":
        return "Unresolved"
    if athlete_splits:
        return "DNF" if session_status == "cancelled" else "In Progress"
    return "DNS"


def _assign_places(rows: list[dict[str, object]], place_key: str) -> None:
    finishers = sorted([row for row in rows if row.get("Status") == "Finished"], key=lambda row: (row["Finish Time Seconds"], row.get("_Finish Event Order") or 0, row["Athlete ID"]))
    last_time = None
    last_place = 0
    for index, row in enumerate(finishers, start=1):
        finish_time = row["Finish Time Seconds"]
        if last_time is None or finish_time != last_time:
            last_place = index
        row[place_key] = last_place
        last_time = finish_time


def _assign_group_places(rows: list[dict[str, object]], group_key: str, place_key: str) -> None:
    groups = sorted({str(row.get(group_key) or "") for row in rows if row.get(group_key)})
    for group in groups:
        group_rows = [row for row in rows if row.get(group_key) == group]
        _assign_places(group_rows, place_key)


def _result_sort_key(row: dict[str, object]) -> tuple[int, float, str]:
    status_rank = {"Finished": 0, "DNF": 1, "Unresolved": 2, "In Progress": 2, "DNS": 3}.get(str(row.get("Status")), 4)
    finish_time = row.get("Finish Time Seconds")
    return (status_rank, float(finish_time) if finish_time is not None else float("inf"), str(row.get("Athlete") or ""))


def _finished_athlete_count(splits: Iterable[SplitRecord], checkpoints: list[Checkpoint]) -> int:
    by_athlete: dict[str, list[SplitRecord]] = {}
    for split in splits:
        by_athlete.setdefault(split.athlete_id, []).append(split)
    return sum(1 for athlete_splits in by_athlete.values() if athlete_finished(athlete_splits, checkpoints))


def _athletes_with_event_fallbacks(athletes: list[Athlete], events: list[SplitEvent]) -> list[Athlete]:
    by_id = {athlete.athlete_id: athlete for athlete in athletes}
    for event in events:
        if event.athlete_id not in by_id:
            by_id[event.athlete_id] = Athlete(
                athlete_id=event.athlete_id,
                name=event.athlete_name or event.athlete_id,
                bib_number=event.bib_number,
                display_order=len(by_id),
            )
    return list(by_id.values())


def _config_stub(checkpoints: list[Checkpoint], race_distance_meters: float):
    from split_tracker.models import MeetConfig

    return MeetConfig(race_distance_meters=race_distance_meters, checkpoints=checkpoints)
