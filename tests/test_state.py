from types import SimpleNamespace

from split_tracker.calculations import generate_checkpoints
from split_tracker.models import Athlete, MeetConfig, RaceClock
from split_tracker.state import elapsed_seconds, is_athlete_finished, record_split, start_race, undo_last_split, validate_setup


class SessionState(SimpleNamespace):
    def setdefault(self, key, value):
        if not hasattr(self, key):
            setattr(self, key, value)
        return getattr(self, key)


def make_session():
    checkpoints = generate_checkpoints(race_distance_meters=800.0, mode="Fixed interval", interval_meters=400.0)
    return SessionState(
        meet_config=MeetConfig(meet_name="City Invite", race_name="Varsity", race_distance_meters=800.0, checkpoints=checkpoints),
        athletes=[Athlete(name="Alex", bib_number="7", target_finish_time_seconds=160.0, athlete_id="a1")],
        splits=[],
        race_clock=RaceClock(),
        last_tap={},
        split_sequence=0,
        message="",
        pending_duplicate=None,
        setup_saved=True,
    )


def test_elapsed_seconds_running_and_paused():
    clock = RaceClock(status="running", start_perf_counter=10.0, paused_total_seconds=2.0)
    assert elapsed_seconds(clock, now=20.0) == 8.0
    paused = RaceClock(status="paused", start_perf_counter=10.0, pause_started_at=18.0, paused_total_seconds=2.0)
    assert elapsed_seconds(paused, now=30.0) == 6.0


def test_record_split_duplicate_lockout_and_record_anyway():
    session = make_session()
    assert start_race(session, now=100.0)
    first = record_split(session, "a1", now=405.0)
    duplicate = record_split(session, "a1", now=406.0)
    override = record_split(session, "a1", now=406.0, record_anyway=True)

    assert first is not None
    assert duplicate is None
    assert override is not None
    assert len(session.splits) == 2
    assert session.splits[-1].is_finish


def test_athlete_completion_prevents_extra_taps():
    session = make_session()
    start_race(session, now=100.0)
    record_split(session, "a1", now=405.0)
    record_split(session, "a1", now=506.0, record_anyway=True)

    blocked = record_split(session, "a1", now=700.0, record_anyway=True)

    assert is_athlete_finished(session, "a1")
    assert blocked is None
    assert len(session.splits) == 2


def test_undo_last_split_recalculates_completion():
    session = make_session()
    start_race(session, now=100.0)
    record_split(session, "a1", now=405.0)
    record_split(session, "a1", now=506.0, record_anyway=True)

    undone = undo_last_split(session)

    assert undone is not None
    assert undone.is_finish
    assert not is_athlete_finished(session, "a1")
    assert len(session.splits) == 1


def test_validate_setup_duplicate_bibs_and_required_fields():
    config = MeetConfig(meet_name="", race_name="", race_distance_meters=800.0, checkpoints=[])
    athletes = [Athlete(name="Alex", bib_number="1"), Athlete(name="Blake", bib_number="1")]

    errors = validate_setup(config, athletes)

    assert "Meet name is required." in errors
    assert "Race name is required." in errors
    assert "At least one checkpoint is required." in errors
    assert "Bib numbers must be unique when entered." in errors
