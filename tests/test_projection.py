from datetime import datetime, timedelta, timezone

from split_tracker.models import Athlete, Checkpoint
from split_tracker.projection import (
    apply_inserted_event_to_projection,
    ordered_timing_athletes,
    project_race_state,
)
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


def test_timing_order_is_untimed_first_then_first_split_fastest():
    session, _, checkpoints = _fixtures()
    athletes = [
        Athlete("Alex", athlete_id="a", display_order=0),
        Athlete("Blair", athlete_id="b", display_order=1),
        Athlete("Casey", athlete_id="c", display_order=2),
        Athlete("Devon", athlete_id="d", display_order=3),
    ]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    projection = project_race_state(session, athletes, checkpoints, [
        _event("a", 10, 62, event_id="a-first", at=now),
        _event("c", 10, 59, event_id="c-first", at=now),
    ])

    assert [item.athlete.athlete_id for item in ordered_timing_athletes(projection)] == ["b", "d", "c", "a"]

    # A later checkpoint and finished status cannot alter first-split order.
    projection = apply_inserted_event_to_projection(
        projection,
        checkpoints,
        _event("c", 20, 130, event_id="c-finish", at=now + timedelta(seconds=1)),
    )
    assert [item.athlete.athlete_id for item in ordered_timing_athletes(projection)] == ["b", "d", "c", "a"]


def test_equal_first_splits_use_roster_position_then_athlete_id():
    session, _, checkpoints = _fixtures()
    # Same persisted display order intentionally exercises the final ID key.
    athletes = [
        Athlete("Zulu", athlete_id="z", display_order=4),
        Athlete("Alpha", athlete_id="a", display_order=4),
    ]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        _event("z", 10, 60, event_id="z-first", at=now),
        _event("a", 10, 60, event_id="a-first", at=now),
    ]
    projection = project_race_state(session, athletes, checkpoints, events)
    # Persisted roster position precedes ID; reconstruction is identical.
    expected = ["z", "a"]
    assert [item.athlete.athlete_id for item in ordered_timing_athletes(projection)] == expected
    rebuilt = project_race_state(session, athletes, checkpoints, list(reversed(events)))
    assert [item.athlete.athlete_id for item in ordered_timing_athletes(rebuilt)] == expected
