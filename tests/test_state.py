from types import SimpleNamespace

from split_tracker.models import Athlete, MeetConfig, RaceClock
from split_tracker.state import elapsed_seconds, record_split, start_race, undo_last_split


class SessionState(SimpleNamespace):
    def setdefault(self, key, value):
        if not hasattr(self, key):
            setattr(self, key, value)
        return getattr(self, key)


def make_session():
    return SessionState(
        meet_config=MeetConfig(race_distance_miles=2.0, checkpoint_distance_miles=1.0),
        athletes=[Athlete(name="Alex", bib_number="7", target_pace_seconds_per_mile=300.0, athlete_id="a1")],
        splits=[],
        race_clock=RaceClock(),
        last_tap={},
        split_sequence=0,
        message="",
    )


def test_elapsed_seconds_running_and_paused():
    clock = RaceClock(status="running", start_perf_counter=10.0, paused_total_seconds=2.0)
    assert elapsed_seconds(clock, now=20.0) == 8.0
    paused = RaceClock(status="paused", start_perf_counter=10.0, pause_started_at=18.0, paused_total_seconds=2.0)
    assert elapsed_seconds(paused, now=30.0) == 6.0


def test_record_split_and_duplicate_lockout():
    session = make_session()
    start_race(session, now=100.0)
    first = record_split(session, "a1", now=405.0)
    duplicate = record_split(session, "a1", now=406.0)

    assert first is not None
    assert first.cumulative_time_seconds == 305.0
    assert duplicate is None
    assert len(session.splits) == 1
    assert session.message == "Duplicate tap ignored."


def test_undo_last_split():
    session = make_session()
    start_race(session, now=100.0)
    record_split(session, "a1", now=405.0)

    undone = undo_last_split(session)

    assert undone is not None
    assert undone.athlete_name == "Alex"
    assert session.splits == []
