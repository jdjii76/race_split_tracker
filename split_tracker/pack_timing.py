"""Validation and synchronization bridge for browser-captured pack events."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from split_tracker.repository import RaceRepository, RepositoryError, SplitEvent


def pack_capture_allowed(
    race_session_id: str | None,
    clock_status: str,
    shared_unavailable: bool,
    timer_name: str,
) -> bool:
    """Allow browser capture only after the authoritative clock is running."""
    return bool(
        race_session_id
        and clock_status == "running"
        and not shared_unavailable
        and timer_name
    )


def expected_arrival_metadata(
    athlete_states,
    checkpoints,
    station_number: int,
) -> dict[str, dict[str, object]]:
    """Describe prior-checkpoint arrival data without changing capture state."""
    ordered_checkpoints = sorted(checkpoints, key=lambda checkpoint: checkpoint.number)
    station_index = next(
        (index for index, checkpoint in enumerate(ordered_checkpoints) if checkpoint.number == station_number),
        None,
    )
    previous = ordered_checkpoints[station_index - 1] if station_index not in {None, 0} else None
    metadata: dict[str, dict[str, object]] = {}
    for roster_index, state in enumerate(athlete_states):
        prior_split = next(
            (
                split
                for split in state.splits
                if previous is not None and split.checkpoint_number == previous.number
            ),
            None,
        )
        latest_split = max(
            state.splits,
            key=lambda split: split.checkpoint_number,
            default=None,
        )
        latest_checkpoint = next(
            (
                checkpoint
                for checkpoint in ordered_checkpoints
                if latest_split is not None and checkpoint.number == latest_split.checkpoint_number
            ),
            None,
        )
        metadata[state.athlete.athlete_id] = {
            "arrival_time": prior_split.cumulative_time_seconds if prior_split else None,
            "missing_previous": previous is not None and prior_split is None,
            "missing_label": previous.label if previous is not None and prior_split is None else "",
            "previous_label": previous.label if previous is not None else "",
            "latest_checkpoint_label": latest_checkpoint.label if latest_checkpoint else "",
            "latest_checkpoint_time": latest_split.cumulative_time_seconds if latest_split else None,
            "roster": roster_index,
        }
    return metadata


def ordered_expected_arrival_states(athlete_states, metadata):
    """Order timed arrivals first, using stable roster order for every tie."""
    return tuple(
        sorted(
            athlete_states,
            key=lambda state: (
                metadata[state.athlete.athlete_id]["arrival_time"] is None,
                metadata[state.athlete.athlete_id]["arrival_time"] or 0,
                metadata[state.athlete.athlete_id]["roster"],
            ),
        )
    )


def normalize_pack_batch(repository: RaceRepository, race_id: str, session_id: str, checkpoint_number: int,
                         payload: list[dict[str, Any]], recorded_by: str) -> list[SplitEvent]:
    """Revalidate an untrusted component payload and submit one idempotent batch."""
    session = repository.get_race_session(session_id)
    if session is None or session.race_id != race_id or session.status != "running":
        raise RepositoryError("Pack capture is stale or the selected race is not running.")
    checkpoints = repository.list_race_session_checkpoints(session_id)
    if checkpoint_number not in {item.checkpoint_sequence for item in checkpoints}:
        raise RepositoryError("Checkpoint does not belong to this race session.")
    athletes = {item.athlete_id for item in repository.list_race_athletes(race_id)}
    clean: list[dict[str, Any]] = []
    for raw in payload[:100]:
        required = {"client_event_id", "athlete_id", "race_session_id", "checkpoint_number", "captured_at", "capture_sequence", "device_id"}
        if not required.issubset(raw) or raw["race_session_id"] != session_id or int(raw["checkpoint_number"]) != checkpoint_number:
            raise RepositoryError("Pack event context does not match the active checkpoint.")
        if str(raw["athlete_id"]) not in athletes:
            raise RepositoryError("Pack event athlete is not eligible for this race.")
        captured = datetime.fromisoformat(str(raw["captured_at"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        # Reject cross-race/stale/future browser storage rather than silently importing it.
        if session.started_at and captured < session.started_at.replace(tzinfo=session.started_at.tzinfo or timezone.utc):
            raise RepositoryError("Pack event predates this race start.")
        clean.append({**raw, "captured_at": captured.isoformat()})
    return repository.record_pack_split_events(session_id, clean, recorded_by)
