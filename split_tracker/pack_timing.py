"""Validation and synchronization bridge for browser-captured pack events."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from split_tracker.repository import RaceRepository, RepositoryError, SplitEvent


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
