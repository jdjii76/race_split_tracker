"""Scheduled-start readiness remains computed and never starts the clock."""
from datetime import datetime, timedelta, timezone

from split_tracker.race_readiness import computed_race_status
from split_tracker.repository import Race, RaceSession


def test_race_becomes_ready_at_five_minute_boundary_without_starting():
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    race = Race(
        meet_id="meet",
        name="Varsity",
        distance_meters=5000,
        scheduled_start=now + timedelta(minutes=10),
    )

    assert computed_race_status(race, now=now) == "Upcoming"
    assert computed_race_status(race, now=now + timedelta(minutes=5)) == "Ready"
    assert race.status == "draft"


def test_manual_session_start_remains_authoritative():
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    race = Race(
        meet_id="meet",
        name="Varsity",
        distance_meters=5000,
        scheduled_start=now + timedelta(minutes=20),
    )
    running = RaceSession(race_id=race.id, status="running", started_at=now)

    assert computed_race_status(race, running, now=now) == "Running"


def test_unscheduled_existing_race_uses_persisted_readiness():
    race = Race(meet_id="meet", name="Varsity", distance_meters=5000, status="ready")

    assert computed_race_status(race) == "Ready"
