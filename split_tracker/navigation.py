"""Pure helpers for the race-day dashboard projection and routing."""
from __future__ import annotations
from collections import defaultdict
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
    category: str
    display_status: str
    is_test: bool

def resolve_active_meet_id(saved_id: str | None, meets: list[Meet]) -> str | None:
    available = {meet.id: meet for meet in meets if meet.status != "archived"}
    if saved_id in available:
        return saved_id
    relevant = [meet for meet in available.values() if meet.status in {"active", "upcoming"}]
    return relevant[0].id if len(relevant) == 1 else None

def determine_race_primary_action(race_status: str, session_status: str | None = None) -> tuple[str, str]:
    category, _ = normalize_dashboard_status(race_status, session_status)
    if category == "completed":
        return "View Results", "results"
    if category == "running":
        return "Open Timing", "live_timing"
    return "Open Race", "meet_setup"


def normalize_dashboard_status(race_status: str, session_status: str | None) -> tuple[str, str]:
    """Map persisted race/session states to the dashboard's three concepts."""
    status = session_status or race_status
    if status in {"running", "paused"}:
        return "running", "Running" if status == "running" else "Paused"
    if status == "completed":
        return "completed", "Finished"
    return "up_next", "Not Started"


def is_test_race(name: str) -> bool:
    """Recognize test races without adding a persisted schema field."""
    return name.lstrip().upper().startswith("TEST")


def dashboard_navigation_ids(summary: RaceDashboardSummary) -> tuple[str, str | None]:
    """Return stable UUIDs for navigation; names are display-only."""
    return summary.race.id, summary.session.id if summary.session else None


def _current_session(sessions: list[RaceSession]) -> RaceSession | None:
    active = [session for session in sessions if session.status in {"ready", "running", "paused"}]
    return (active or sessions)[-1] if sessions else None


def build_race_dashboard_summaries(
    races: list[Race], sessions: list[RaceSession], athlete_counts: dict[str, int]
) -> list[RaceDashboardSummary]:
    """Build isolated summaries by stable race UUID from batched persisted data."""
    sessions_by_race: dict[str, list[RaceSession]] = defaultdict(list)
    race_ids = {race.id for race in races}
    for session in sessions:
        if session.race_id in race_ids:
            sessions_by_race[session.race_id].append(session)
    for race_sessions in sessions_by_race.values():
        race_sessions.sort(key=lambda item: (item.created_at, item.id))

    summaries = []
    for race in races:
        session = _current_session(sessions_by_race[race.id])
        session_status = session.status if session else None
        category, display_status = normalize_dashboard_status(race.status, session_status)
        label, destination = determine_race_primary_action(race.status, session_status)
        summaries.append(RaceDashboardSummary(
            race=race,
            athlete_count=athlete_counts.get(race.id, 0),
            session=session,
            status=session_status or race.status,
            action_label=label,
            destination=destination,
            category=category,
            display_status=display_status,
            is_test=is_test_race(race.name),
        ))
    return summaries

def get_meet_race_summaries(repository, meet_id: str) -> tuple[list[RaceDashboardSummary], list[str]]:
    races = [race for race in repository.list_races_for_meet(meet_id) if race.status != "archived"]
    race_ids = [race.id for race in races]
    if not race_ids:
        return [], []
    sessions = repository.list_race_sessions_for_races(race_ids)
    counts = repository.count_race_athletes_for_races(race_ids)
    return build_race_dashboard_summaries(races, sessions, counts), []
