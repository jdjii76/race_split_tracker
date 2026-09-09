"""Safe, canonical race-day roster mutations.

The helpers in this module deliberately mutate only ``race_athletes`` membership.
They never create permanent athletes or copy timing/result events between sessions.
"""
from __future__ import annotations

from dataclasses import dataclass

from split_tracker.auth import AppIdentity
from split_tracker.repository import Race, RaceRepository, RepositoryError


TIMING_DATA_MESSAGE = (
    "This athlete already has timing data in this race and cannot be changed directly. "
    "Use Manage Results to resolve the existing race record before changing participation."
)
DESTINATION_CLOSED_MESSAGE = "That race can no longer accept race-day roster changes."


@dataclass(frozen=True)
class RosterChange:
    """Counts returned after a successful canonical membership mutation."""

    source_count: int
    destination_count: int | None = None


def can_manage_race_day_roster(identity: AppIdentity | None) -> bool:
    """Roster management is independent of timing mode and limited to staff."""
    return bool(identity and identity.role in {"coach", "admin"})


def _require_manager(identity: AppIdentity | None) -> None:
    if not can_manage_race_day_roster(identity):
        raise RepositoryError("Coach or administrator access is required to manage race rosters.")


def _sessions(repository: RaceRepository, race_id: str):
    return repository.list_race_sessions_for_race(race_id)


def athlete_has_timing_data(repository: RaceRepository, race_id: str, athlete_id: str) -> bool:
    """Include append-only splits, outcomes, and result history in the safety check."""
    for session in _sessions(repository, race_id):
        if any(event.athlete_id == athlete_id for event in repository.list_all_split_events(session.id)):
            return True
        if any(outcome.athlete_id == athlete_id for outcome in repository.list_race_athlete_outcomes(session.id)):
            return True
        if repository.list_result_events(session.id, athlete_id):
            return True
    return False


def race_accepts_athletes(repository: RaceRepository, race: Race) -> bool:
    """Running races accept safe late adds; review/final states never do."""
    if race.status in {"completed", "archived"}:
        return False
    return not any(session.status in {"awaiting_review", "completed", "cancelled"} for session in _sessions(repository, race.id))


def eligible_destination_races(repository: RaceRepository, source: Race) -> list[Race]:
    """Return open races in the same meet, preserving configured display order."""
    return [
        race for race in repository.list_races_for_meet(source.meet_id)
        if race.id != source.id and race_accepts_athletes(repository, race)
    ]


def add_athlete(repository: RaceRepository, race: Race, athlete_id: str, identity: AppIdentity | None) -> RosterChange:
    _require_manager(identity)
    if not race_accepts_athletes(repository, race):
        raise RepositoryError(DESTINATION_CLOSED_MESSAGE)
    permanent = repository.get_athlete(athlete_id)
    if permanent is None:
        raise RepositoryError("Athlete was not found in the permanent roster.")
    if permanent.status == "archived":
        raise RepositoryError("Archived athletes cannot be added. Restore the athlete first.")
    ids = repository.list_race_athlete_ids(race.id)
    if athlete_id not in ids:
        repository.replace_race_athletes_from_roster(race.id, [*ids, athlete_id])
    return RosterChange(len(repository.list_race_athletes(race.id, include_inactive=True)))


def remove_athlete(repository: RaceRepository, race: Race, athlete_id: str, identity: AppIdentity | None) -> RosterChange:
    _require_manager(identity)
    if athlete_has_timing_data(repository, race.id, athlete_id):
        raise RepositoryError(TIMING_DATA_MESSAGE)
    repository.delete_race_athlete(race.id, athlete_id)
    return RosterChange(len(repository.list_race_athletes(race.id, include_inactive=True)))


def move_athlete(
    repository: RaceRepository,
    source: Race,
    destination: Race,
    athlete_id: str,
    identity: AppIdentity | None,
) -> RosterChange:
    """Move membership only; event history remains attached to its original session."""
    _require_manager(identity)
    if source.meet_id != destination.meet_id or source.id == destination.id:
        raise RepositoryError("Athletes can only be moved to another race in this meet.")
    if not race_accepts_athletes(repository, destination):
        raise RepositoryError(DESTINATION_CLOSED_MESSAGE)
    if athlete_has_timing_data(repository, source.id, athlete_id):
        raise RepositoryError(TIMING_DATA_MESSAGE)
    if athlete_id not in repository.list_race_athlete_ids(source.id):
        raise RepositoryError("Athlete is no longer entered in the source race. Refresh and try again.")

    destination_ids = repository.list_race_athlete_ids(destination.id)
    added = athlete_id not in destination_ids
    if added:
        add_athlete(repository, destination, athlete_id, identity)
    try:
        repository.delete_race_athlete(source.id, athlete_id)
    except Exception:
        # Best-effort compensation for repositories without a transaction API.
        if added:
            repository.delete_race_athlete(destination.id, athlete_id)
        raise
    return RosterChange(
        len(repository.list_race_athletes(source.id, include_inactive=True)),
        len(repository.list_race_athletes(destination.id, include_inactive=True)),
    )
