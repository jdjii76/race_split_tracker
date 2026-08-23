"""Race-day timer option projection tests."""
from split_tracker.models import Checkpoint
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession
from split_tracker.timer_mode import build_timer_options, race_is_available


def test_timer_options_only_include_active_meets_and_available_races():
    repository = InMemoryRaceRepository()
    active = repository.create_meet(Meet(name="Invitational", status="active"))
    completed = repository.create_meet(Meet(name="Old Meet", status="completed"))
    ready_race = repository.create_race(Race(meet_id=active.id, name="Boys Varsity", race_category="Varsity", distance_meters=5000, status="ready"))
    repository.create_race(Race(meet_id=completed.id, name="Old Race", distance_meters=5000, status="ready"))

    options = build_timer_options(repository)

    assert [option.race.id for option in options] == [ready_race.id]
    assert options[0].status_label == "Ready"
    assert options[0].checkpoints


def test_timer_option_uses_authoritative_session_checkpoint_snapshot():
    repository = InMemoryRaceRepository()
    meet = repository.create_meet(Meet(name="Invitational", status="active"))
    race = repository.create_race(Race(meet_id=meet.id, name="Girls Varsity", distance_meters=5000, status="ready"))
    session = repository.create_race_session(RaceSession(race_id=race.id, status="running"))
    repository.create_race_session_checkpoints(session.id, [Checkpoint(1, "2 Mile", 3218.688), Checkpoint(2, "Finish", 5000, is_finish=True)])

    option = build_timer_options(repository)[0]

    assert option.session == session
    assert [checkpoint.label for checkpoint in option.checkpoints] == ["2 Mile", "Finish"]
    assert race_is_available(race, session)
