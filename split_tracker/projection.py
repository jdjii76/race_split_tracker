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


def first_split_order_key(
    athlete_state: ProjectedAthleteState,
    roster_order: int,
) -> tuple[int, float, int, str]:
    """Sort untimed athletes first, then by persisted first-split time."""
    first_time = (
        athlete_state.splits[0].cumulative_time_seconds
        if athlete_state.splits
        else float("inf")
    )
    return (
        1 if athlete_state.splits else 0,
        first_time,
        roster_order,
        athlete_state.athlete.athlete_id,
    )


def ordered_timing_athletes(
    projection: ProjectedRaceState,
) -> tuple[ProjectedAthleteState, ...]:
    """Return the live display order without changing the persisted roster."""
    roster_positions = {
        state.athlete.athlete_id: index
        for index, state in enumerate(projection.athletes)
    }
    return tuple(
        sorted(
            projection.athletes,
            key=lambda state: first_split_order_key(
                state, roster_positions[state.athlete.athlete_id]
            ),
        )
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
        (event for event in split_events if event.race_session_id == race_session.id and not event.is_deleted),
        key=split_event_sort_key,
    )
    checkpoint_by_number = {checkpoint.number: checkpoint for checkpoint in checkpoints}
    accepted: list[SplitEvent] = []
    accepted_by_athlete: dict[str, list[SplitEvent]] = {athlete.athlete_id: [] for athlete in race_athletes}
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
        status = "FINISHED" if finished else f"Next: {next_cp.label if next_cp else '—'}"
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
    return ProjectedRaceState(race_session, tuple(projected_athletes), tuple(accepted), tuple(results))
