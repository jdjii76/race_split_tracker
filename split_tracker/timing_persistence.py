"""Helpers for persisting and restoring live timing state."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from split_tracker.calculations import build_split_record, recalculate_athlete_splits
from split_tracker.models import Athlete, MeetConfig, RaceClock, SplitRecord
from split_tracker.repository import RaceRepository, RaceSession, RepositoryError, SplitEvent
from split_tracker.session_checkpoints import get_session_checkpoints

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


def persisted_elapsed_seconds(session: RaceSession, now: datetime | None = None) -> float:
    """Return persisted race elapsed time without relying on Streamlit state."""
    current = utc_now() if now is None else now
    if session.status == "running" and session.started_at is not None:
        return max(0.0, session.elapsed_offset_seconds + (current - session.started_at).total_seconds())
    return max(0.0, session.elapsed_offset_seconds)


def race_clock_from_session(session: RaceSession, *, now_perf: float | None = None, now_utc: datetime | None = None) -> RaceClock:
    """Create the local perf_counter-based RaceClock from a persisted session."""
    perf = time.perf_counter() if now_perf is None else now_perf
    elapsed = persisted_elapsed_seconds(session, now_utc)
    if session.status == "running":
        return RaceClock(status="running", start_perf_counter=perf - elapsed, paused_total_seconds=0.0)
    if session.status == "paused":
        return RaceClock(status="paused", start_perf_counter=perf - elapsed, pause_started_at=perf, paused_total_seconds=0.0)
    if session.status == "completed":
        return RaceClock(status="ended", ended_elapsed_seconds=elapsed)
    return RaceClock()


def split_event_from_record(record: SplitRecord, *, race_session_id: str) -> SplitEvent:
    """Create a persisted split event from a visible split record."""
    return SplitEvent(
        id=record.split_id,
        race_session_id=race_session_id,
        athlete_id=record.athlete_id,
        athlete_name=record.athlete_name,
        bib_number=record.bib_number,
        checkpoint_number=record.checkpoint_number,
        checkpoint_label=record.checkpoint_label,
        elapsed_seconds=record.cumulative_time_seconds,
        event_order=record.sequence,
    )


def rebuild_splits_from_events(
    *,
    events: list[SplitEvent],
    athletes: list[Athlete],
    config: MeetConfig,
) -> list[SplitRecord]:
    """Rebuild visible SplitRecord objects from persisted active events."""
    athletes_by_id = {athlete.athlete_id: athlete for athlete in athletes}
    rebuilt_by_athlete: dict[str, list[SplitRecord]] = {}
    ordered_events = sorted(events, key=lambda event: (event.event_order, event.recorded_at, event.id))
    for event in ordered_events:
        athlete = athletes_by_id.get(event.athlete_id) or Athlete(name=event.athlete_name or event.athlete_id, bib_number=event.bib_number, athlete_id=event.athlete_id)
        previous = rebuilt_by_athlete.setdefault(event.athlete_id, [])
        split = build_split_record(
            split_id=event.id,
            athlete=athlete,
            existing_athlete_splits=previous,
            checkpoints=config.checkpoints,
            elapsed_seconds=event.elapsed_seconds,
            race_distance_meters=config.race_distance_meters,
            sequence=event.event_order,
        )
        if split is not None:
            previous.append(split)
    return sorted([split for splits in rebuilt_by_athlete.values() for split in splits], key=lambda split: split.sequence)


def refresh_splits_from_repository(session_state) -> None:
    """Restore active split events into session-state visible split records."""
    repository: RaceRepository | None = session_state.repository
    race_session_id = session_state.get("active_race_session_id")
    if repository is None or not race_session_id:
        return
    events = repository.list_active_split_events(race_session_id)
    race_session = repository.get_race_session(race_session_id)
    if race_session is not None:
        checkpoint_result = get_session_checkpoints(repository, race_session, session_state.meet_config.checkpoints)
        session_state.meet_config.checkpoints = checkpoint_result.checkpoints
    session_state.splits = rebuild_splits_from_events(events=events, athletes=session_state.athletes, config=session_state.meet_config)
    session_state.split_sequence = max([event.event_order for event in repository.list_all_split_events(race_session_id)] or [0])


def restore_timing_state(session_state, *, now_perf: float | None = None, now_utc: datetime | None = None) -> RaceSession | None:
    """Restore persisted timing state for the selected race, if one exists."""
    repository: RaceRepository | None = session_state.repository
    race_id = session_state.get("selected_race_id")
    if repository is None or not race_id:
        return None
    try:
        race_session = repository.get_active_or_latest_race_session_for_race(race_id)
        if race_session is None:
            return None
        session_state.active_race_session_id = race_session.id
        session_state.race_clock = race_clock_from_session(race_session, now_perf=now_perf, now_utc=now_utc)
        refresh_splits_from_repository(session_state)
        return race_session
    except Exception:
        logger.exception("Failed to restore timing state", extra={"race_id": race_id})
        raise


def persist_start(session_state, *, now_perf: float | None = None, now_utc: datetime | None = None) -> RaceSession | None:
    """Create and persist a new running race session for the selected race."""
    repository: RaceRepository | None = session_state.repository
    race_id = session_state.get("selected_race_id")
    if repository is None or not race_id:
        return None
    current = utc_now() if now_utc is None else now_utc
    session = repository.create_started_race_session_with_checkpoints(
        RaceSession(race_id=race_id, status="running", started_at=current, elapsed_offset_seconds=0.0),
        session_state.meet_config.checkpoints,
    )
    session_state.active_race_session_id = session.id
    return session


def persist_pause(session_state, elapsed_seconds: float, *, now_utc: datetime | None = None) -> RaceSession | None:
    repository: RaceRepository | None = session_state.repository
    race_session_id = session_state.get("active_race_session_id")
    if repository is None or not race_session_id:
        return None
    session = repository.get_race_session(race_session_id)
    if session is None:
        raise RepositoryError("Race session not found.")
    saved = repository.update_race_session(replace(session, status="paused", paused_at=utc_now() if now_utc is None else now_utc, elapsed_offset_seconds=elapsed_seconds))
    return saved


def persist_resume(session_state, *, now_utc: datetime | None = None) -> RaceSession | None:
    repository: RaceRepository | None = session_state.repository
    race_session_id = session_state.get("active_race_session_id")
    if repository is None or not race_session_id:
        return None
    session = repository.get_race_session(race_session_id)
    if session is None:
        raise RepositoryError("Race session not found.")
    return repository.update_race_session(replace(session, status="running", started_at=utc_now() if now_utc is None else now_utc, paused_at=None))


def persist_completion(session_state, elapsed_seconds: float, *, now_utc: datetime | None = None) -> RaceSession | None:
    repository: RaceRepository | None = session_state.repository
    race_session_id = session_state.get("active_race_session_id")
    if repository is None or not race_session_id:
        return None
    session = repository.get_race_session(race_session_id)
    if session is None:
        raise RepositoryError("Race session not found.")
    return repository.update_race_session(replace(session, status="completed", ended_at=utc_now() if now_utc is None else now_utc, paused_at=None, elapsed_offset_seconds=elapsed_seconds))


def persist_cancel(session_state, elapsed_seconds: float, *, now_utc: datetime | None = None) -> RaceSession | None:
    repository: RaceRepository | None = session_state.repository
    race_session_id = session_state.get("active_race_session_id")
    if repository is None or not race_session_id:
        return None
    session = repository.get_race_session(race_session_id)
    if session is None:
        raise RepositoryError("Race session not found.")
    return repository.update_race_session(replace(session, status="cancelled", ended_at=utc_now() if now_utc is None else now_utc, paused_at=None, elapsed_offset_seconds=elapsed_seconds))


def persist_split_record(session_state, record: SplitRecord) -> SplitEvent | None:
    """Persist one visible split record as one split event."""
    repository: RaceRepository | None = session_state.repository
    race_session_id = session_state.get("active_race_session_id")
    if repository is None or not race_session_id:
        return None
    return repository.create_split_event(split_event_from_record(record, race_session_id=race_session_id))


def persist_undo_split(session_state, split: SplitRecord) -> SplitEvent | None:
    """Soft-delete a persisted split event and rebuild visible state."""
    repository: RaceRepository | None = session_state.repository
    if repository is None or not session_state.get("active_race_session_id"):
        return None
    event = repository.soft_delete_split_event(split.split_id)
    refresh_splits_from_repository(session_state)
    return event
