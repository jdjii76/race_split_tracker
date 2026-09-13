from datetime import datetime, timedelta, timezone

import pytest

from split_tracker.models import Checkpoint
from split_tracker.repository import (
    InMemoryRaceRepository,
    Meet,
    Race,
    RaceSession,
    RepositoryError,
    SplitEvent,
)
from split_tracker.station_health import activity_age_label, station_connection_state


def _station_repository():
    repository = InMemoryRaceRepository()
    meet = repository.create_meet(Meet("Invitational"))
    race = repository.create_race(Race(meet.id, "Varsity 5K", 5000))
    session = repository.create_race_session(RaceSession(race.id, status="running"))
    repository.create_race_session_checkpoints(
        session.id, [Checkpoint(1, "Mile 1", 1609), Checkpoint(2, "Mile 2", 3218)]
    )
    return repository, session


def test_connection_state_and_activity_age_use_heartbeat_age():
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    assert station_connection_state(now - timedelta(seconds=20), now=now) == "Active"
    assert station_connection_state(now - timedelta(seconds=90), now=now) == "Waiting"
    assert station_connection_state(now - timedelta(minutes=4), now=now) == "Offline"
    assert station_connection_state(None, now=now) == "Offline"
    assert activity_age_label(now - timedelta(seconds=10), now=now) == "10 seconds ago"
    assert activity_age_label(now - timedelta(minutes=3), now=now) == "3 minutes ago"


def test_station_health_derives_capture_count_and_latest_athlete_from_events():
    repository, session = _station_repository()
    repository.assign_timer_station(session.id, 1, "mile-one-device")
    repository.assign_timer_station(session.id, 2, "mile-two-device")
    first = datetime(2026, 8, 24, 12, 1, tzinfo=timezone.utc)
    repository.create_split_event(SplitEvent(
        session.id, "a1", 1, 360, 1, athlete_name="John Smith",
        checkpoint_label="Mile 1", capture_mode="pack", device_id="mile-one-device",
        received_at=first,
    ))
    repository.create_split_event(SplitEvent(
        session.id, "a2", 1, 361, 2, athlete_name="Sarah Jones",
        checkpoint_label="Mile 1", capture_mode="pack", device_id="mile-one-device",
        received_at=first + timedelta(seconds=1),
    ))

    stations = repository.list_timer_station_health(session.id)

    assert [station.checkpoint_label for station in stations] == ["Mile 1", "Mile 2"]
    assert stations[0].capture_count == 2
    assert stations[0].latest_athlete_name == "Sarah Jones"
    assert stations[0].last_capture_at == first + timedelta(seconds=1)
    assert stations[1].capture_count == 0


def test_heartbeat_requires_the_devices_exact_station_assignment():
    repository, session = _station_repository()
    repository.assign_timer_station(session.id, 1, "assigned-device")

    repository.heartbeat_timer_station(session.id, 1, "assigned-device")
    with pytest.raises(RepositoryError, match="not assigned"):
        repository.heartbeat_timer_station(session.id, 2, "assigned-device")
    with pytest.raises(RepositoryError, match="not assigned"):
        repository.heartbeat_timer_station(session.id, 1, "another-device")

