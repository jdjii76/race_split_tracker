"""Race-day timer option projection tests."""
import pytest

from split_tracker.models import Checkpoint
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession
from split_tracker.timer_mode import build_timer_options, race_is_available


def _race_with_session(meet_status: str, session_status: str):
    repository = InMemoryRaceRepository()
    meet = repository.create_meet(Meet(name="Invitational", status=meet_status))
    race = repository.create_race(
        Race(meet_id=meet.id, name="Varsity", distance_meters=5000)
    )
    session = repository.create_race_session(
        RaceSession(race_id=race.id, status=session_status)
    )
    return repository, race, session


def test_active_meet_with_running_session_appears():
    repository, race, session = _race_with_session("active", "running")

    options = build_timer_options(repository)

    assert [(option.race.id, option.session.id) for option in options] == [(race.id, session.id)]


def test_upcoming_meet_with_ready_session_appears():
    repository, race, session = _race_with_session("upcoming", "ready")

    options = build_timer_options(repository)

    assert [(option.race.id, option.session.id) for option in options] == [(race.id, session.id)]


def test_draft_meet_with_running_session_appears():
    repository, race, session = _race_with_session("draft", "running")

    options = build_timer_options(repository)

    assert [(option.race.id, option.session.id) for option in options] == [(race.id, session.id)]


def test_draft_meet_without_available_race_does_not_appear():
    repository = InMemoryRaceRepository()
    meet = repository.create_meet(Meet(name="Draft Meet", status="draft"))
    repository.create_race(
        Race(meet_id=meet.id, name="Draft Race", distance_meters=5000, status="draft")
    )

    assert build_timer_options(repository) == []


def test_archived_meet_does_not_appear():
    repository, _, _ = _race_with_session("archived", "running")

    assert build_timer_options(repository) == []


def test_ready_race_without_a_session_appears():
    repository = InMemoryRaceRepository()
    meet = repository.create_meet(Meet(name="Draft Meet", status="draft"))
    race = repository.create_race(
        Race(meet_id=meet.id, name="Ready Race", distance_meters=5000, status="ready")
    )

    assert [option.race.id for option in build_timer_options(repository)] == [race.id]


@pytest.mark.parametrize("session_status", ["completed", "cancelled"])
def test_completed_or_cancelled_session_does_not_appear(session_status):
    repository, _, _ = _race_with_session("active", session_status)

    assert build_timer_options(repository) == []


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
