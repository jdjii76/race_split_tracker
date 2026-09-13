"""Computed race-day readiness without mutating persisted lifecycle state."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from split_tracker.repository import Race, RaceSession

READY_WINDOW = timedelta(minutes=5)


def computed_race_status(
    race: Race,
    session: RaceSession | None = None,
    *,
    now: datetime | None = None,
) -> str:
    """Return the display status for a race at ``now``.

    Persisted session lifecycle states remain authoritative. A scheduled but
    unstarted race becomes ready only inside its five-minute start window.
    """
    session_status = session.status if session else None
    if session_status == "running":
        return "Running"
    if session_status == "paused":
        return "Paused"
    if session_status == "awaiting_review":
        return "Awaiting Review"
    if session_status == "completed" or race.status == "completed":
        return "Completed"
    if session_status == "cancelled":
        return "Cancelled"

    if race.scheduled_start is not None:
        current = now or datetime.now(timezone.utc)
        scheduled = race.scheduled_start
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        else:
            scheduled = scheduled.astimezone(timezone.utc)
        return "Upcoming" if current < scheduled - READY_WINDOW else "Ready"

    status = session_status or race.status
    return {
        "ready": "Ready",
        "running": "Running",
        "paused": "Paused",
        "awaiting_review": "Awaiting Review",
        "completed": "Completed",
    }.get(status, "Upcoming")
