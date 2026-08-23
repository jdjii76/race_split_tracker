from datetime import datetime, timedelta, timezone

from split_tracker.models import Athlete, Checkpoint
from split_tracker.projection import (
    apply_inserted_event_to_projection,
    athlete_matches_search,
    latest_projected_split,
    ordered_race_board_athletes,
    ordered_timing_athletes,
    partition_finished_athletes,
    project_race_state,
)
from split_tracker.repository import RaceSession, SplitEvent


def _fixtures():
    session = RaceSession(
        race_id="race",
        id="session",
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    athletes = [Athlete("Alex", athlete_id="a"), Athlete("Blair", athlete_id="b")]
    checkpoints = [
        Checkpoint(10, "Mile 1", 1609.344),
        Checkpoint(20, "Finish", 3200, True),
    ]
    return session, athletes, checkpoints


def _event(
    athlete: str,
    checkpoint: int,
    seconds: float,
    *,
    event_id: str,
    at: datetime,
    session="session",
    event_order=99
):
    return SplitEvent(
        id=event_id,
        race_session_id=session,
        athlete_id=athlete,
        checkpoint_number=checkpoint,
        elapsed_seconds=seconds,
        event_order=event_order,
        recorded_at=at,
        created_at=at,
    )


def test_projection_empty_and_next_checkpoint():
    session, athletes, checkpoints = _fixtures()
    state = project_race_state(session, athletes, checkpoints, [])
    assert state.results_rows == ()
    assert [item.next_checkpoint.number for item in state.athletes] == [10, 10]
    assert all(item.button_enabled for item in state.athletes)


def test_projection_keeps_mile_two_when_mile_one_is_missing():
    session, athletes, _ = _fixtures()
    checkpoints = [
        Checkpoint(1, "Mile 1", 1609),
        Checkpoint(2, "Mile 2", 3218),
        Checkpoint(3, "Finish", 5000, True),
    ]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    state = project_race_state(
        session,
        athletes,
        checkpoints,
        [_event("a", 2, 765, event_id="mile-two", at=now, event_order=1)],
    )

    alex = state.athletes[0]
    assert [(split.checkpoint_number, split.cumulative_time_seconds) for split in alex.splits] == [(2, 765)]
    assert alex.next_checkpoint.number == 1
    assert not alex.finished


def test_projection_keeps_finish_when_both_intermediate_splits_are_missing():
    session, athletes, _ = _fixtures()
    checkpoints = [
        Checkpoint(1, "Mile 1", 1609),
        Checkpoint(2, "Mile 2", 3218),
        Checkpoint(3, "Finish", 5000, True),
    ]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    state = project_race_state(
        session,
        athletes,
        checkpoints,
        [_event("a", 3, 1292, event_id="finish-only", at=now, event_order=1)],
    )

    alex = state.athletes[0]
    assert [(split.checkpoint_number, split.cumulative_time_seconds) for split in alex.splits] == [(3, 1292)]
    assert alex.next_checkpoint.number == 1
    assert alex.finished


def test_projection_orders_filters_and_deduplicates_persisted_events():
    session, athletes, checkpoints = _fixtures()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        _event(
            "a",
            20,
            120,
            event_id="finish",
            at=now + timedelta(seconds=2),
            event_order=4,
        ),
        _event(
            "a",
            10,
            61,
            event_id="duplicate",
            at=now + timedelta(seconds=1),
            event_order=3,
        ),
        _event("b", 10, 59, event_id="blair", at=now, event_order=2),
        _event("a", 10, 60, event_id="first", at=now, event_order=1),
        _event("a", 10, 58, event_id="foreign", at=now, session="other", event_order=1),
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
        _event(
            "a",
            20,
            120,
            event_id="second",
            at=aware + timedelta(seconds=1),
            event_order=0,
        ),
        _event(
            "a", 10, 60, event_id="first", at=aware.replace(tzinfo=None), event_order=0
        ),
    ]
    assert (
        project_race_state(session, athletes, checkpoints, events).athletes[0].finished
    )


def test_event_order_overrides_reversed_client_era_timestamps():
    session, athletes, checkpoints = _fixtures()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        _event("a", 20, 120, event_id="second", at=now, event_order=2),
        _event(
            "a", 10, 60, event_id="first", at=now + timedelta(hours=8), event_order=1
        ),
    ]

    projected = project_race_state(session, athletes, checkpoints, events)

    assert [event.id for event in projected.events] == ["first", "second"]
    assert projected.athletes[0].finished


def test_stable_timing_order_does_not_move_after_a_split():
    session, _, checkpoints = _fixtures()
    athletes = [
        Athlete("Alex", athlete_id="a", display_order=0),
        Athlete("Blair", athlete_id="b", display_order=1),
        Athlete("Casey", athlete_id="c", display_order=2),
        Athlete("Devon", athlete_id="d", display_order=3),
    ]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    projection = project_race_state(
        session,
        athletes,
        checkpoints,
        [
            _event("a", 10, 62, event_id="a-first", at=now),
            _event("c", 10, 59, event_id="c-first", at=now),
        ],
    )

    expected = ["a", "b", "c", "d"]
    assert [
        item.athlete.athlete_id for item in ordered_timing_athletes(projection)
    ] == expected

    # A later checkpoint and finished status cannot alter stable roster order.
    projection = apply_inserted_event_to_projection(
        projection,
        checkpoints,
        _event("c", 20, 130, event_id="c-finish", at=now + timedelta(seconds=1)),
    )
    assert [
        item.athlete.athlete_id for item in ordered_timing_athletes(projection)
    ] == expected


def test_expected_arrival_groups_next_checkpoints_but_preserves_roster_order():
    session, _, checkpoints = _fixtures()
    # Same persisted display order intentionally exercises the final ID key.
    athletes = [
        Athlete("Zulu", athlete_id="z", display_order=4),
        Athlete("Alpha", athlete_id="a", display_order=4),
    ]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [_event("a", 10, 60, event_id="a-first", at=now)]
    projection = project_race_state(session, athletes, checkpoints, events)
    expected = ["a", "z"]
    assert [
        item.athlete.athlete_id
        for item in ordered_timing_athletes(projection, "Expected Arrival")
    ] == expected
    rebuilt = project_race_state(session, athletes, checkpoints, list(reversed(events)))
    assert [
        item.athlete.athlete_id
        for item in ordered_timing_athletes(rebuilt, "Expected Arrival")
    ] == expected


def test_live_board_orders_by_progress_then_cumulative_time():
    session, _, checkpoints = _fixtures()
    athletes = [
        Athlete("Alex", athlete_id="a"),
        Athlete("Blair", athlete_id="b"),
        Athlete("Casey", athlete_id="c"),
    ]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    projection = project_race_state(
        session,
        athletes,
        checkpoints,
        [
            _event("a", 10, 55, event_id="a-one", at=now, event_order=1),
            _event("b", 10, 58, event_id="b-one", at=now, event_order=2),
            _event("b", 20, 121, event_id="b-two", at=now, event_order=3),
            _event("c", 10, 57, event_id="c-one", at=now, event_order=4),
            _event("c", 20, 119, event_id="c-two", at=now, event_order=5),
        ],
    )

    ordered = ordered_race_board_athletes(projection)
    assert [item.athlete.athlete_id for item in ordered] == ["c", "b", "a"]
    active, finished = partition_finished_athletes(ordered)
    assert [item.athlete.athlete_id for item in active] == ["a"]
    assert [item.athlete.athlete_id for item in finished] == ["c", "b"]


def test_name_and_bib_search_and_authoritative_button_state():
    session, _, checkpoints = _fixtures()
    projection = project_race_state(
        session,
        [Athlete("Jordan Smith", bib_number="42", athlete_id="j")],
        checkpoints,
        [],
    )
    state = projection.athletes[0]

    assert athlete_matches_search(state, "jordan")
    assert athlete_matches_search(state, "42")
    assert not athlete_matches_search(state, "99")
    assert "Next: Mile 1" in state.button_label


def test_latest_projected_split_uses_global_event_order_not_per_athlete_sequence():
    session, _, checkpoints = _fixtures()
    athletes = [Athlete("Alex", athlete_id="a"), Athlete("Blair", athlete_id="b")]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    projection = project_race_state(
        session,
        athletes,
        checkpoints,
        [
            _event("a", 10, 50, event_id="a-first", at=now, event_order=1),
            _event("a", 20, 100, event_id="a-finish", at=now, event_order=2),
            _event("b", 10, 110, event_id="b-latest", at=now, event_order=3),
        ],
    )

    latest = latest_projected_split(projection)

    assert latest is not None
    assert latest.split_id == "b-latest"
    assert latest.athlete_id == "b"
