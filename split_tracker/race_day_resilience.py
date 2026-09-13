"""Pure policy helpers for durable Race Day queue recovery and station telemetry."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

PENDING_STATES = frozenset({"pending", "failed"})
QUEUE_SCHEMA_VERSION = 2
SYNC_FAILURE_DEGRADED_THRESHOLD = 2


def deterministic_pending_events(events: Iterable[dict], race_session_id: str) -> list[dict]:
    """Return retryable events in stable device order without changing timestamps."""
    unique: dict[str, dict] = {}
    for event in events:
        event_id = str(event.get("client_event_id") or "")
        if event_id and event.get("race_session_id") == race_session_id and event.get("state", "pending") in PENDING_STATES:
            unique[event_id] = dict(event)
    return sorted(unique.values(), key=lambda event: (
        str(event.get("device_id") or ""),
        int(event.get("capture_sequence") or 0),
        str(event.get("captured_at") or ""),
        str(event.get("client_event_id") or ""),
    ))


def connection_label(*, browser_online: bool, pending_count: int, syncing: bool = False,
                     consecutive_failures: int = 0) -> tuple[str, str]:
    """Describe browser and server connectivity without trusting navigator alone."""
    if not browser_online:
        return "offline", f"Offline · {pending_count} saved on this device"
    if consecutive_failures >= SYNC_FAILURE_DEGRADED_THRESHOLD:
        return "degraded", f"Connection problem · {pending_count} saved on this device"
    if syncing and pending_count:
        return "syncing", f"Online · Syncing {pending_count}"
    return "online", "Online · All synced" if not pending_count else f"Online · {pending_count} saved on this device"


@dataclass(frozen=True)
class FinalizationRisk:
    checkpoint_label: str
    state: str
    detail: str


def finalization_risks(stations, *, local_pending: int = 0, now: datetime | None = None) -> list[FinalizationRisk]:
    """Explain known/unknown sync risk; telemetry is never treated as canonical data."""
    from split_tracker.station_health import activity_age_label, station_connection_state

    current = now or datetime.now(timezone.utc)
    risks: list[FinalizationRisk] = []
    if local_pending:
        risks.append(FinalizationRisk("This device", "pending", f"{local_pending} capture(s) are saved locally and not confirmed synchronized."))
    for station in stations:
        state = station_connection_state(station.last_seen, now=current)
        pending = getattr(station, "pending_sync_count", None)
        if state == "Offline":
            known = f"last reported {pending} pending" if pending is not None else "pending count unknown"
            risks.append(FinalizationRisk(station.checkpoint_label, "offline", f"Offline; last seen {activity_age_label(station.last_seen, now=current)}; {known}. This device may contain unsynchronized timing events."))
        elif pending:
            risks.append(FinalizationRisk(station.checkpoint_label, "pending", f"Online; last reported {pending} pending capture(s)."))
        elif getattr(station, "client_connection_state", "") in {"degraded", "offline"}:
            risks.append(FinalizationRisk(station.checkpoint_label, "degraded", "The last client report indicated a connection problem."))
    return risks
