"""Helpers for persisting and restoring live timing state."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4

from split_tracker.calculations import build_split_record
from split_tracker.models import Athlete, MeetConfig, RaceClock, SplitRecord
from split_tracker.repository import RaceRepository, RaceSession, RepositoryError, SplitEvent
from split_tracker.projection import apply_inserted_event_to_projection, project_race_state
from split_tracker.session_checkpoints import get_session_checkpoints

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SplitActionResult:
    """Outcome of one authoritative athlete-button action."""

    status: str
    event: SplitEvent | None = None
    message: str = ""


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


def synchronize_shared_timing(session_state, *, now_perf: float | None = None, now_utc: datetime | None = None) -> RaceSession:
    """Atomically reload the shared session and events, leaving visible state intact on failure."""
    repository: RaceRepository | None = session_state.repository
    race_session_id = session_state.get("active_race_session_id")
    if repository is None or not race_session_id:
        raise RepositoryError("No shared race session is connected.")
    race_session = repository.get_race_session(race_session_id)
    if race_session is None:
        raise RepositoryError("The connected race session no longer exists.")
    events = repository.list_active_split_events(race_session_id)
    all_events = repository.list_all_split_events(race_session_id)
    # The roster is shared race data too; never let a browser's stale setup copy
    # decide which persisted split controls or results exist.
    persisted_athletes = repository.list_race_athletes(race_session.race_id)
    # Older sessions created before race rosters were introduced still carry
    # athlete identity in their split rows. Keep that migration path working;
    # current sessions always use the persisted roster.
    athletes = persisted_athletes or list(session_state.athletes)
    checkpoint_result = get_session_checkpoints(repository, race_session, session_state.meet_config.checkpoints)
    projection = project_race_state(race_session, athletes, checkpoint_result.checkpoints, events)
    rebuilt = list(projection.results_rows)
    session_state.athletes = athletes
    session_state.projected_race_state = projection
    session_state.meet_config.checkpoints = checkpoint_result.checkpoints
    session_state.splits = rebuilt
    session_state.split_sequence = max([event.event_order for event in all_events] or [0])
    session_state.race_clock = race_clock_from_session(race_session, now_perf=now_perf, now_utc=now_utc)
    session_state.last_sync_at = utc_now()
    session_state.storage_connected = True
    session_state.sync_error = ""
    session_state.persisted_race_status = race_session.status
    session_state.persisted_started_at = race_session.started_at
    session_state.loaded_split_event_count = len(events)
    session_state.latest_event_id = ""
    session_state.latest_event_at = None
    session_state.latest_shared_action = ""
    if session_state.get("selected_race_id"):
        session_state.timing_restored_for_race_id = session_state.selected_race_id
    if events:
        latest = max(events, key=lambda event: (event.recorded_at, event.event_order))
        session_state.latest_event_id = latest.id
        session_state.latest_event_at = latest.recorded_at
        session_state.latest_shared_action = f"{latest.athlete_name} • {latest.checkpoint_label}" + (f" • {latest.recorded_by}" if latest.recorded_by else "")
    return race_session


def poll_shared_timing(session_state, *, now_perf: float | None = None, now_utc: datetime | None = None) -> RaceSession | None:
    """Run one observable poll attempt and preserve the last good state on failure."""
    session_state.poll_cycle_at = utc_now() if now_utc is None else now_utc
    session_state.poll_cycle_count = session_state.get("poll_cycle_count", 0) + 1
    try:
        return synchronize_shared_timing(session_state, now_perf=now_perf, now_utc=now_utc)
    except Exception as exc:
        session_state.storage_connected = False
        session_state.sync_error = str(exc)
        logger.warning(
            "Shared timing poll failed",
            extra={
                "race_session_id": session_state.get("active_race_session_id"),
                "timer_name": session_state.get("timer_name", ""),
                "poll_cycle_count": session_state.poll_cycle_count,
            },
        )
        return None


def start_and_synchronize_shared_timing(
    session_state,
    *,
    now_perf: float | None = None,
    now_utc: datetime | None = None,
) -> RaceSession:
    """Persist a start, then enter the same authoritative path as polling clients."""
    started = persist_start(session_state, now_perf=now_perf, now_utc=now_utc)
    if started is None:
        raise RepositoryError("Shared race could not be started.")
    # Never apply the write response as a separate starter-only state. Reload the
    # exact selected row and its active events just as a waiting browser does.
    synchronized = synchronize_shared_timing(session_state, now_perf=now_perf, now_utc=now_utc)
    session_state.initiated_start_session_id = synchronized.id
    return synchronized


def record_authoritative_split(
    session_state,
    athlete_id: str,
    *,
    now_utc: datetime | None = None,
) -> SplitActionResult:
    """Persist one split using the loaded projection and one authoritative RPC."""
    action_started = time.perf_counter()
    repository: RaceRepository | None = session_state.repository
    race_session_id = session_state.get("active_race_session_id")
    action_at = utc_now() if now_utc is None else now_utc
    projection = session_state.get("projected_race_state")
    # Compatibility/recovery path for callers that have not yet loaded the
    # controlled live fragment. Normal button actions always have a projection.
    if projection is None and repository is not None and race_session_id:
        synchronize_shared_timing(session_state, now_utc=action_at)
        projection = session_state.get("projected_race_state")
    athlete_state = next(
        (item for item in projection.athletes if item.athlete.athlete_id == athlete_id),
        None,
    ) if projection else None
    athlete = athlete_state.athlete if athlete_state else None
    diagnostics = {
        "timer_name": session_state.get("timer_name", ""),
        "athlete_id": athlete_id,
        "athlete_name": athlete.name if athlete else "",
        "race_session_id": race_session_id or "",
        "click_received_at": action_at,
        "checkpoint_number": None,
        "checkpoint_label": "",
        "elapsed_seconds": None,
        "result": "validating",
        "inserted_event_id": "",
        "events_after_reload": session_state.get("loaded_split_event_count", 0),
        "error": "",
        "timings_ms": {"button_handler_start": 0.0},
    }
    session_state.last_split_action = diagnostics
    validation_started = time.perf_counter()
    if repository is None or not race_session_id:
        diagnostics.update(result="error", error="No shared race session is connected.")
        raise RepositoryError(diagnostics["error"])
    if athlete is None or athlete_state is None:
        diagnostics.update(result="error", error="Athlete not found.")
        raise RepositoryError(diagnostics["error"])

    race_session = projection.race_session
    if race_session.status != "running" or race_session.started_at is None:
        diagnostics.update(result="error", error="Splits can only be recorded while the shared race is running.")
        raise RepositoryError(diagnostics["error"])
    diagnostics["timings_ms"]["pre_insert_validation"] = (time.perf_counter() - validation_started) * 1000
    athlete_splits = list(athlete_state.splits)
    record = build_split_record(
        split_id=str(uuid4()),
        athlete=athlete,
        existing_athlete_splits=athlete_splits,
        checkpoints=session_state.meet_config.checkpoints,
        elapsed_seconds=persisted_elapsed_seconds(race_session, action_at),
        race_distance_meters=session_state.meet_config.race_distance_meters,
        sequence=max([event.event_order for event in projection.events] or [0]) + 1,
    )
    if record is None:
        diagnostics.update(result="error", error=f"{athlete.name} has no remaining checkpoints.")
        raise RepositoryError(diagnostics["error"])
    diagnostics.update(
        checkpoint_number=record.checkpoint_number,
        checkpoint_label=record.checkpoint_label,
        elapsed_seconds=record.cumulative_time_seconds,
    )
    event = replace(
        split_event_from_record(record, race_session_id=race_session_id),
        recorded_by=session_state.get("timer_name", ""),
        recorded_at=action_at,
    )
    try:
        insert_started = time.perf_counter()
        saved = repository.create_split_event(event)
        diagnostics["timings_ms"]["supabase_insert_rpc"] = (time.perf_counter() - insert_started) * 1000
    except RepositoryError as exc:
        diagnostics["timings_ms"]["supabase_insert_rpc"] = (time.perf_counter() - insert_started) * 1000
        if any(term in str(exc).lower() for term in ("already", "duplicate", "conflict", "invalid", "checkpoint", "running")):
            sync_started = time.perf_counter()
            synchronize_shared_timing(session_state, now_utc=action_at)
            diagnostics["timings_ms"]["post_insert_synchronization"] = (time.perf_counter() - sync_started) * 1000
            diagnostics.update(
                result="duplicate",
                error=str(exc),
                events_after_reload=session_state.loaded_split_event_count,
            )
            return SplitActionResult(status="duplicate", message=str(exc))
        diagnostics.update(result="error", error=str(exc))
        raise
    rebuild_started = time.perf_counter()
    updated = apply_inserted_event_to_projection(
        projection, session_state.meet_config.checkpoints, saved
    )
    session_state.projected_race_state = updated
    session_state.splits = list(updated.results_rows)
    session_state.split_sequence = max(session_state.split_sequence, saved.event_order)
    session_state.loaded_split_event_count = len(updated.events)
    session_state.latest_event_id = saved.id
    session_state.latest_event_at = saved.recorded_at
    session_state.latest_shared_action = f"{saved.athlete_name} • {saved.checkpoint_label}"
    diagnostics["timings_ms"]["projection_rebuild"] = (time.perf_counter() - rebuild_started) * 1000
    diagnostics["timings_ms"]["post_insert_synchronization"] = 0.0
    diagnostics.update(
        result="inserted",
        inserted_event_id=saved.id,
        events_after_reload=session_state.loaded_split_event_count,
    )
    diagnostics["timings_ms"]["total_action"] = (time.perf_counter() - action_started) * 1000
    return SplitActionResult(status="inserted", event=saved, message=f"Recorded {athlete.name} at {record.checkpoint_label}.")


def rebuild_splits_from_events(
    *,
    events: list[SplitEvent],
    athletes: list[Athlete],
    config: MeetConfig,
    use_event_checkpoint_identity: bool = False,
) -> list[SplitRecord]:
    """Rebuild visible splits, optionally matching persisted checkpoint identity.

    Live timing always enables identity matching against its session snapshot.
    The positional default remains only for reconstruction of legacy sessions
    whose historical events may reference checkpoint numbers no longer present.
    """
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
            checkpoint_number=event.checkpoint_number if use_event_checkpoint_identity else None,
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
    session_state.splits = rebuild_splits_from_events(
        events=events,
        athletes=session_state.athletes,
        config=session_state.meet_config,
        use_event_checkpoint_identity=True,
    )
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
    """Atomically connect to or create the selected race's active session."""
    repository: RaceRepository | None = session_state.repository
    race_id = session_state.get("selected_race_id")
    if repository is None or not race_id:
        return None
    current = utc_now() if now_utc is None else now_utc
    session = repository.get_or_create_active_race_session(
        race_id, session_state.meet_config.checkpoints
    )
    session_state.active_race_session_id = session.id
    session_state.race_clock = race_clock_from_session(
        session, now_perf=now_perf, now_utc=current
    )
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
    event = split_event_from_record(record, race_session_id=race_session_id)
    event = replace(event, recorded_by=session_state.get("timer_name", ""))
    saved = repository.create_split_event(event)
    refresh_splits_from_repository(session_state)
    session_state.latest_shared_action = f"{saved.athlete_name} • {saved.checkpoint_label} • {saved.recorded_by or 'anonymous'}"
    return saved


def persist_undo_split(session_state, split: SplitRecord) -> SplitEvent | None:
    """Soft-delete a persisted split event and rebuild visible state."""
    repository: RaceRepository | None = session_state.repository
    if repository is None or not session_state.get("active_race_session_id"):
        return None
    event = repository.soft_delete_split_event(split.split_id)
    refresh_splits_from_repository(session_state)
    return event
