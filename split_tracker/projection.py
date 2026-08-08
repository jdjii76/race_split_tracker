"""Pure projection of persisted live-race data into one UI-ready snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from split_tracker.calculations import build_split_record
from split_tracker.models import Athlete, Checkpoint, MeetConfig, SplitRecord
from split_tracker.repository import RaceSession, SplitEvent


def _utc(value: datetime) -> datetime:
    """Normalize naive legacy values and aware values for stable comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def split_event_sort_key(event: SplitEvent) -> tuple[int, int, datetime, datetime, str]:
    """Prefer authoritative sequence, with timestamps only for legacy rows."""
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    if event.event_order > 0:
        return (0, event.event_order, epoch, epoch, event.id)
    return (1, 0, _utc(event.recorded_at), _utc(event.created_at), event.id)


@dataclass(frozen=True)
class ProjectedAthleteState:
    athlete: Athlete
    completed_split_count: int
    next_checkpoint: Checkpoint | None
    latest_split_event: SplitEvent | None
    latest_elapsed_seconds: float | None
    finished: bool
    button_enabled: bool
    button_label: str
    splits: tuple[SplitRecord, ...]


@dataclass(frozen=True)
class ProjectedRaceState:
    race_session: RaceSession
    athletes: tuple[ProjectedAthleteState, ...]
    events: tuple[SplitEvent, ...]
    results_rows: tuple[SplitRecord, ...]


def race_progress_order_key(
    athlete_state: ProjectedAthleteState,
) -> tuple[int, float, str, str]:
    """Rank current race progress using only the authoritative projection."""
    return (
        -athlete_state.completed_split_count,
        (
            athlete_state.latest_elapsed_seconds
            if athlete_state.latest_elapsed_seconds is not None
            else float("inf")
        ),
        athlete_state.athlete.name.casefold(),
        athlete_state.athlete.athlete_id,
    )


def ordered_timing_athletes(
    projection: ProjectedRaceState,
    mode: str = "Stable",
) -> tuple[ProjectedAthleteState, ...]:
    """Return a button order without changing the persisted race roster.

    Stable is deliberately the default: recording a split does not move any
    unrelated button. Expected Arrival groups athletes by their next checkpoint
    while preserving roster order inside each group. Race Order mirrors the
    progress-ranked live board.
    """
    if mode == "Stable":
        return projection.athletes
    roster_positions = {
        state.athlete.athlete_id: index
        for index, state in enumerate(projection.athletes)
    }
    if mode == "Expected Arrival":
        return tuple(
            sorted(
                projection.athletes,
                key=lambda state: (
                    -state.completed_split_count,
                    roster_positions[state.athlete.athlete_id],
                    state.athlete.athlete_id,
                ),
            )
        )
    if mode != "Race Order":
        raise ValueError(f"Unknown timing order mode: {mode}")
    return tuple(sorted(projection.athletes, key=race_progress_order_key))


def ordered_race_board_athletes(
    projection: ProjectedRaceState,
) -> tuple[ProjectedAthleteState, ...]:
    """Return athletes in current-progress order for the live race board."""
    return tuple(sorted(projection.athletes, key=race_progress_order_key))


def athlete_matches_search(
    athlete_state: ProjectedAthleteState,
    query: str,
) -> bool:
    """Match a race-day search against athlete name or bib number."""
    normalized = query.strip().casefold()
    if not normalized:
        return True
    return (
        normalized in athlete_state.athlete.name.casefold()
        or normalized in str(athlete_state.athlete.bib_number or "").casefold()
    )


def partition_finished_athletes(
    athlete_states: tuple[ProjectedAthleteState, ...] | list[ProjectedAthleteState],
) -> tuple[tuple[ProjectedAthleteState, ...], tuple[ProjectedAthleteState, ...]]:
    """Separate active timing targets from de-emphasized finishers."""
    active = tuple(state for state in athlete_states if not state.finished)
    finished = tuple(state for state in athlete_states if state.finished)
    return active, finished


def latest_projected_split(
    projection: ProjectedRaceState | None,
) -> SplitRecord | None:
    """Return the visible split belonging to the latest accepted event."""
    if projection is None or not projection.events:
        return None
    latest_event_id = projection.events[-1].id
    return next(
        (
            split
            for split in projection.results_rows
            if split.split_id == latest_event_id
        ),
        None,
    )


def apply_inserted_event_to_projection(
    projection: ProjectedRaceState,
    checkpoints: list[Checkpoint],
    event: SplitEvent,
) -> ProjectedRaceState:
    """Deterministically replay one RPC-returned event into a local snapshot."""
    return project_race_state(
        projection.race_session,
        [state.athlete for state in projection.athletes],
        checkpoints,
        [*projection.events, event],
    )


def project_race_state(
    race_session: RaceSession,
    race_athletes: list[Athlete],
    checkpoints: list[Checkpoint],
    split_events: list[SplitEvent],
) -> ProjectedRaceState:
    """Build all live controls and results from one persisted-data snapshot.

    Invalid-session events, duplicate checkpoint events, and events that skip the
    athlete's next checkpoint are ignored. This makes replay deterministic even
    for legacy rows created before the database uniqueness constraint existed.
    """
    ordered = sorted(
        (
            event
            for event in split_events
            if event.race_session_id == race_session.id and not event.is_deleted
        ),
        key=split_event_sort_key,
    )
    checkpoint_by_number = {checkpoint.number: checkpoint for checkpoint in checkpoints}
    accepted: list[SplitEvent] = []
    accepted_by_athlete: dict[str, list[SplitEvent]] = {
        athlete.athlete_id: [] for athlete in race_athletes
    }
    for event in ordered:
        history = accepted_by_athlete.get(event.athlete_id)
        if history is None or len(history) >= len(checkpoints):
            continue
        expected = checkpoints[len(history)]
        if event.checkpoint_number != expected.number:
            continue
        history.append(event)
        accepted.append(event)

    race_distance = checkpoints[-1].distance_meters if checkpoints else 0.0
    config = MeetConfig(race_distance_meters=race_distance, checkpoints=checkpoints)
    projected_athletes: list[ProjectedAthleteState] = []
    results: list[SplitRecord] = []
    for athlete in race_athletes:
        records: list[SplitRecord] = []
        history = accepted_by_athlete[athlete.athlete_id]
        for sequence, event in enumerate(history, start=1):
            checkpoint = checkpoint_by_number[event.checkpoint_number]
            record = build_split_record(
                split_id=event.id,
                athlete=athlete,
                existing_athlete_splits=records,
                checkpoints=config.checkpoints,
                elapsed_seconds=event.elapsed_seconds,
                race_distance_meters=config.race_distance_meters,
                sequence=sequence,
                checkpoint_number=checkpoint.number,
            )
            if record is not None:
                records.append(record)
        next_cp = checkpoints[len(records)] if len(records) < len(checkpoints) else None
        latest = history[-1] if history else None
        finished = next_cp is None and bool(checkpoints)
        status = (
            "FINISHED" if finished else f"Next: {next_cp.label if next_cp else '—'}"
        )
        last_line = ""
        if records:
            last = records[-1]
            last_line = f"\nLast: {last.segment_split_seconds:.1f}s • Cum: {last.cumulative_time_seconds:.1f}s"
        projected_athletes.append(
            ProjectedAthleteState(
                athlete=athlete,
                completed_split_count=len(records),
                next_checkpoint=next_cp,
                latest_split_event=latest,
                latest_elapsed_seconds=latest.elapsed_seconds if latest else None,
                finished=finished,
                button_enabled=race_session.status == "running" and next_cp is not None,
                button_label=f"{athlete.name}\nBib {athlete.bib_number or '—'} • {status}{last_line}",
                splits=tuple(records),
            )
        )
        results.extend(records)
    results.sort(key=lambda split: (split.cumulative_time_seconds, split.split_id))
    return ProjectedRaceState(
        race_session, tuple(projected_athletes), tuple(accepted), tuple(results)
    )
