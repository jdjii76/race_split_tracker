"""Pure selection and presentation helpers for persisted timing corrections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from split_tracker.repository import SplitEvent


@dataclass(frozen=True)
class TimingActivity:
    occurred_at: datetime
    event_id: str
    label: str
    is_correction: bool


def latest_active_event(events: list[SplitEvent] | tuple[SplitEvent, ...], race_session_id: str) -> SplitEvent | None:
    eligible = [event for event in events if event.race_session_id == race_session_id and not event.is_deleted]
    return max(eligible, key=lambda event: (event.event_order, event.recorded_at, event.id), default=None)


def active_events_for_athlete(events, race_session_id: str, athlete_id: str) -> list[SplitEvent]:
    return sorted(
        [event for event in events if event.race_session_id == race_session_id and event.athlete_id == athlete_id and not event.is_deleted],
        key=lambda event: (event.checkpoint_number, event.event_order, event.id),
    )


def recent_timing_activity(events, race_session_id: str, *, limit: int = 8) -> list[TimingActivity]:
    activity: list[TimingActivity] = []
    for event in events:
        if event.race_session_id != race_session_id:
            continue
        if event.is_deleted and event.corrected_at:
            actor = f" by {event.corrected_by}" if event.corrected_by else ""
            activity.append(TimingActivity(
                event.corrected_at,
                event.id,
                f"Correction — {event.athlete_name} {event.checkpoint_label} undone{actor}",
                True,
            ))
        elif not event.is_deleted:
            prefix = "Manual — " if event.correction_type == "manual" else ""
            activity.append(TimingActivity(
                event.recorded_at,
                event.id,
                f"{prefix}{event.athlete_name} — {event.checkpoint_label}",
                event.correction_type == "manual",
            ))
    return sorted(activity, key=lambda item: (item.occurred_at, item.event_id), reverse=True)[:max(0, limit)]
