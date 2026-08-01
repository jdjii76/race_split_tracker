"""Pure helpers for the race-day meet dashboard and routing."""
from __future__ import annotations
from dataclasses import dataclass
from split_tracker.repository import Meet, Race, RaceSession

@dataclass(frozen=True)
class RaceDashboardSummary:
    race: Race
    athlete_count: int
    session: RaceSession | None
    status: str
    action_label: str
    destination: str

def resolve_active_meet_id(saved_id: str | None, meets: list[Meet]) -> str | None:
    available = {meet.id: meet for meet in meets if meet.status != "archived"}
    if saved_id in available:
        return saved_id
    relevant = [meet for meet in available.values() if meet.status in {"active", "upcoming"}]
    return relevant[0].id if len(relevant) == 1 else None

def determine_race_primary_action(race_status: str, session_status: str | None = None) -> tuple[str, str]:
    status = session_status or race_status
    if status == "completed":
        return "View Results", "results"
    if status in {"running", "paused"}:
        return "Resume Timing", "live_timing"
    return "Start Timing", "live_timing"

def get_meet_race_summaries(repository, meet_id: str) -> tuple[list[RaceDashboardSummary], list[str]]:
    summaries, errors = [], []
    for race in repository.list_races_for_meet(meet_id):
        try:
            athletes = repository.list_race_athletes(race.id, include_inactive=False)
            session = repository.get_active_or_latest_race_session_for_race(race.id)
            status = session.status if session else race.status
            label, destination = determine_race_primary_action(race.status, session.status if session else None)
            summaries.append(RaceDashboardSummary(race, len(athletes), session, status, label, destination))
        except Exception as exc:
            errors.append(f"{race.name}: {exc}")
            label, destination = determine_race_primary_action(race.status)
            summaries.append(RaceDashboardSummary(race, 0, None, race.status, label, destination))
    return summaries, errors
