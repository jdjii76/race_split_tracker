"""Race-day timer option projection tests."""
from datetime import datetime, timedelta, timezone

import pytest

from split_tracker.models import Checkpoint
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession
from split_tracker.timer_mode import build_timer_options, race_is_available, station_label


@pytest.mark.parametrize(
    ("checkpoint", "expected"),
    [
        (Checkpoint(1, "1 mile", 1609.344), "Mile 1 Split"),
        (Checkpoint(2, "2 miles", 3218.688), "Mile 2 Split"),
        (Checkpoint(3, "3 miles", 4828.032), "Mile 3 Split"),
        (Checkpoint(4, "Finish", 5000, is_finish=True), "Finish Line"),
    ],
)
def test_station_label_uses_volunteer_friendly_wording(checkpoint, expected):
    assert station_label(checkpoint) == expected


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


def test_scheduled_race_is_upcoming_then_ready_five_minutes_before_start():
    repository = InMemoryRaceRepository()
    meet = repository.create_meet(Meet(name="Invitational", status="upcoming"))
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    race = repository.create_race(Race(
        meet_id=meet.id,
        name="Varsity",
        distance_meters=5000,
        scheduled_start=now + timedelta(minutes=10),
    ))

    upcoming = build_timer_options(repository, now=now)[0]
    ready = build_timer_options(repository, now=now + timedelta(minutes=5))[0]

    assert upcoming.race.id == race.id
    assert upcoming.status_label == "Upcoming"
    assert ready.status_label == "Ready"
    assert upcoming.session is None and ready.session is None


def test_only_finish_station_opens_when_scheduled_race_becomes_ready():
    repository = InMemoryRaceRepository()
    meet = repository.create_meet(Meet(name="Invitational", status="active"))
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    repository.create_race(Race(
        meet_id=meet.id,
        name="Varsity",
        distance_meters=5000,
        scheduled_start=now + timedelta(minutes=5),
    ))

    option = build_timer_options(repository, now=now)[0]
    finish = next(checkpoint for checkpoint in option.checkpoints if checkpoint.is_finish)
    split = next(checkpoint for checkpoint in option.checkpoints if not checkpoint.is_finish)

    assert option.station_is_open(finish)
    assert not option.station_is_open(split)


def test_existing_unscheduled_ready_race_keeps_finish_starter_workflow():
    repository = InMemoryRaceRepository()
    meet = repository.create_meet(Meet(name="Invitational", status="active"))
    repository.create_race(Race(
        meet_id=meet.id, name="Varsity", distance_meters=5000, status="ready"
    ))

    option = build_timer_options(repository)[0]
    finish = next(checkpoint for checkpoint in option.checkpoints if checkpoint.is_finish)

    assert option.status_label == "Ready"
    assert option.station_is_open(finish)
    assert option.session is None
