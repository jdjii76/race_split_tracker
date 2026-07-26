from datetime import datetime, timedelta, timezone

from split_tracker.models import Athlete, Checkpoint
from split_tracker.projection import project_race_state
from split_tracker.repository import RaceSession, SplitEvent


def _fixtures():
    session = RaceSession(race_id="race", id="session", status="running", started_at=datetime.now(timezone.utc))
    athletes = [Athlete("Alex", athlete_id="a"), Athlete("Blair", athlete_id="b")]
    checkpoints = [Checkpoint(10, "Mile 1", 1609.344), Checkpoint(20, "Finish", 3200, True)]
    return session, athletes, checkpoints


def _event(athlete: str, checkpoint: int, seconds: float, *, event_id: str, at: datetime, session="session"):
    return SplitEvent(
        id=event_id,
        race_session_id=session,
        athlete_id=athlete,
        checkpoint_number=checkpoint,
        elapsed_seconds=seconds,
        event_order=99,
        recorded_at=at,
        created_at=at,
    )


def test_projection_empty_and_next_checkpoint():
    session, athletes, checkpoints = _fixtures()
    state = project_race_state(session, athletes, checkpoints, [])
    assert state.results_rows == ()
    assert [item.next_checkpoint.number for item in state.athletes] == [10, 10]
    assert all(item.button_enabled for item in state.athletes)


def test_projection_orders_filters_and_deduplicates_persisted_events():
    session, athletes, checkpoints = _fixtures()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        _event("a", 20, 120, event_id="finish", at=now + timedelta(seconds=2)),
        _event("a", 10, 61, event_id="duplicate", at=now + timedelta(seconds=1)),
        _event("b", 10, 59, event_id="blair", at=now),
        _event("a", 10, 60, event_id="first", at=now),
        _event("a", 10, 58, event_id="foreign", at=now, session="other"),
    ]
    state = project_race_state(session, athletes, checkpoints, events)
    alex, blair = state.athletes
    assert alex.finished and alex.completed_split_count == 2
    assert alex.latest_split_event.id == "finish"
    assert blair.next_checkpoint.number == 20
    assert {row.split_id for row in state.results_rows} == {"first", "finish", "blair"}
    assert len(state.events) == len(state.results_rows) == 3


def test_projection_normalizes_naive_and_aware_timestamps():
    session, athletes, checkpoints = _fixtures()
    aware = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        _event("a", 20, 120, event_id="second", at=aware + timedelta(seconds=1)),
        _event("a", 10, 60, event_id="first", at=aware.replace(tzinfo=None)),
    ]
    assert project_race_state(session, athletes, checkpoints, events).athletes[0].finished
