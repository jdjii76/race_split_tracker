"""Application service for controlled race-result reassignment."""
from __future__ import annotations

from dataclasses import dataclass

from split_tracker.auth import AppIdentity
from split_tracker.repository import RaceRepository, RepositoryError, ResultReassignment


DEFAULT_REASON = "Wrong athlete selected during race"


@dataclass(frozen=True)
class ReassignmentPreview:
    source_name: str
    destination_name: str
    timing_event_count: int
    has_finish: bool
    destination_will_be_added: bool


def _require_staff(identity: AppIdentity | None) -> AppIdentity:
    if identity is None or identity.role not in {"coach", "admin"}:
        raise RepositoryError("Coach or administrator access is required to reassign results.")
    return identity


def preview_reassignment(repository: RaceRepository, session_id: str, source_id: str, destination_id: str) -> ReassignmentPreview:
    session = repository.get_race_session(session_id)
    if session is None:
        raise RepositoryError("Race session not found.")
    roster = repository.list_race_athletes(session.race_id, include_inactive=True)
    source = next((item for item in roster if item.athlete_id == source_id), None)
    destination = repository.get_athlete(destination_id)
    if source is None or destination is None:
        raise RepositoryError("Select valid source and destination athletes.")
    events = [item for item in repository.list_active_split_events(session_id) if item.athlete_id == source_id]
    result = next((item for item in repository.list_result_events(session_id) if item.athlete_id == source_id), None)
    checkpoints = {item.checkpoint_sequence: item for item in repository.list_race_session_checkpoints(session_id)}
    has_finish = bool(result and result.status == "finished") or any(checkpoints.get(item.checkpoint_number) and checkpoints[item.checkpoint_number].is_finish for item in events)
    return ReassignmentPreview(source.name, destination.display_name, len(events), has_finish,
                               destination_id not in {item.athlete_id for item in roster})


def reassign_result(
    repository: RaceRepository, session_id: str, source_id: str, destination_id: str,
    reason: str, identity: AppIdentity | None,
) -> ResultReassignment:
    identity = _require_staff(identity)
    if not reason.strip():
        raise RepositoryError("A correction reason is required.")
    return repository.reassign_race_result(ResultReassignment(
        race_session_id=session_id, original_athlete_id=source_id,
        destination_athlete_id=destination_id, reason=reason.strip(),
        performed_by=identity.user_id,
    ))
