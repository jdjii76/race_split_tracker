"""Pure timer-station health projections for race-day displays."""
from __future__ import annotations

from datetime import datetime, timezone


def station_connection_state(last_seen: datetime | None, *, now: datetime | None = None) -> str:
    """Classify a station heartbeat without changing persisted state."""
    if last_seen is None:
        return "Offline"
    current = now or datetime.now(timezone.utc)
    seen = last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=timezone.utc)
    age = max(0.0, (current - seen).total_seconds())
    if age <= 60:
        return "Active"
    if age <= 180:
        return "Waiting"
    return "Offline"


def activity_age_label(value: datetime | None, *, now: datetime | None = None) -> str:
    if value is None:
        return "No activity"
    current = now or datetime.now(timezone.utc)
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    seconds = max(0, int((current - moment).total_seconds()))
    if seconds < 60:
        return f"{seconds} seconds ago"
    minutes = seconds // 60
    return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
