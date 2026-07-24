"""Authoritative checkpoint access for persisted race sessions."""

from __future__ import annotations

from dataclasses import dataclass

from split_tracker.models import Checkpoint
from split_tracker.repository import RaceRepository, RaceSession, RaceSessionCheckpoint


@dataclass(frozen=True)
class SessionCheckpointResult:
    """Checkpoint list plus source used for one race session."""

    checkpoints: list[Checkpoint]
    source: str


def snapshots_to_checkpoints(snapshots: list[RaceSessionCheckpoint]) -> list[Checkpoint]:
    """Convert persisted snapshot rows into calculation Checkpoint objects."""
    return [
        Checkpoint(
            number=snapshot.checkpoint_sequence,
            label=snapshot.label,
            distance_meters=snapshot.distance_meters,
            is_finish=snapshot.is_finish,
        )
        for snapshot in sorted(snapshots, key=lambda item: (item.checkpoint_sequence, item.id))
    ]


def get_session_checkpoints(
    repository: RaceRepository,
    session: RaceSession,
    fallback_checkpoints: list[Checkpoint],
) -> SessionCheckpointResult:
    """Return the authoritative checkpoints for a race session.

    Persisted race-session checkpoint snapshots are authoritative. Legacy sessions
    without snapshots use the provided fallback checkpoints without writing new
    snapshot rows, because historical race configuration may have changed.
    """
    snapshots = repository.list_race_session_checkpoints(session.id)
    if snapshots:
        return SessionCheckpointResult(checkpoints=snapshots_to_checkpoints(snapshots), source="snapshot")
    return SessionCheckpointResult(checkpoints=fallback_checkpoints, source="legacy_fallback")
