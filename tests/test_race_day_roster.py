"""Race-day roster safety and authorization tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from split_tracker.auth import AppIdentity
from split_tracker.models import PermanentAthlete
from split_tracker.race_day_roster import add_athlete, eligible_destination_races, move_athlete, remove_athlete
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, RepositoryError, ResultEvent, SplitEvent


COACH = AppIdentity("coach-id", "coach@example.com", "coach")
ADMIN = AppIdentity("admin-id", "admin@example.com", "admin")
TIMER = AppIdentity("timer-id", "timer@example.com", "timer")


@pytest.fixture
def race_day():
    repository = InMemoryRaceRepository()
    meet = repository.create_meet(Meet(name="Invitational"))
    race_a = repository.create_race(Race(meet_id=meet.id, name="Girls JV", distance_meters=5000))
    race_b = repository.create_race(Race(meet_id=meet.id, name="Girls Varsity", distance_meters=5000, display_order=1))
    sarah = repository.create_athlete(PermanentAthlete(first_name="Sarah", last_name="Jones", team_division="Swing"))
    mia = repository.create_athlete(PermanentAthlete(first_name="Mia", last_name="Lee", team_division="JV"))
    archived = repository.create_athlete(PermanentAthlete(first_name="Alex", last_name="Old", status="archived"))
    return repository, meet, race_a, race_b, sarah, mia, archived


def test_add_and_remove_before_start_updates_count_without_changing_permanent_roster(race_day):
    repository, _, race, _, sarah, mia, archived = race_day
    permanent_before = dict(repository.athletes)

    assert add_athlete(repository, race, sarah.id, COACH).source_count == 1
    assert add_athlete(repository, race, mia.id, COACH).source_count == 2
    assert add_athlete(repository, race, sarah.id, COACH).source_count == 2
    assert remove_athlete(repository, race, mia.id, ADMIN).source_count == 1

    assert repository.list_race_athlete_ids(race.id) == [sarah.id]
    assert repository.athletes == permanent_before
    assert archived not in repository.list_athletes()
    with pytest.raises(RepositoryError, match="Archived"):
        add_athlete(repository, race, archived.id, COACH)


def test_move_before_start_preserves_id_and_membership(race_day):
    repository, _, source, destination, sarah, *_ = race_day
    add_athlete(repository, source, sarah.id, COACH)

    change = move_athlete(repository, source, destination, sarah.id, COACH)

    assert change == (change.__class__)(0, 1)
    assert sarah.id not in repository.list_race_athlete_ids(source.id)
    assert repository.list_race_athlete_ids(destination.id) == [sarah.id]
    assert repository.get_athlete(sarah.id) == sarah


def test_late_add_remove_and_move_without_timing_data(race_day):
    repository, _, source, destination, sarah, mia, _ = race_day
    add_athlete(repository, source, sarah.id, COACH)
    add_athlete(repository, source, mia.id, COACH)
    repository.create_race_session(RaceSession(race_id=source.id, status="running", started_at=datetime.now(timezone.utc)))

    assert remove_athlete(repository, source, mia.id, COACH).source_count == 1
    assert move_athlete(repository, source, destination, sarah.id, COACH).destination_count == 1
    # A running destination uses the same safe late-add rule and creates no history.
    repository.create_race_session(RaceSession(race_id=source.id, status="running", started_at=datetime.now(timezone.utc)))
    add_athlete(repository, source, mia.id, ADMIN)
    assert repository.list_all_split_events(repository.list_race_sessions_for_race(source.id)[0].id) == []


@pytest.mark.parametrize("operation", ["remove", "move"])
def test_timing_data_rejects_source_membership_change_and_preserves_events(race_day, operation):
    repository, _, source, destination, sarah, *_ = race_day
    add_athlete(repository, source, sarah.id, COACH)
    session = repository.create_race_session(RaceSession(race_id=source.id, status="running", started_at=datetime.now(timezone.utc)))
    event = repository.create_split_event(SplitEvent(race_session_id=session.id, athlete_id=sarah.id, checkpoint_number=1, elapsed_seconds=300, event_order=1))

    with pytest.raises(RepositoryError, match="Manage Results"):
        if operation == "remove":
            remove_athlete(repository, source, sarah.id, COACH)
        else:
            move_athlete(repository, source, destination, sarah.id, COACH)

    assert repository.list_race_athlete_ids(source.id) == [sarah.id]
    assert repository.list_all_split_events(session.id) == [event]


def test_result_history_also_blocks_removal(race_day):
    repository, _, source, _, sarah, *_ = race_day
    add_athlete(repository, source, sarah.id, COACH)
    session = repository.create_race_session(RaceSession(race_id=source.id, status="completed", started_at=datetime.now(timezone.utc)))
    repository.result_events["result"] = ResultEvent(id="result", race_session_id=session.id, athlete_id=sarah.id, status="dns", source="official")
    with pytest.raises(RepositoryError, match="Manage Results"):
        remove_athlete(repository, source, sarah.id, COACH)


@pytest.mark.parametrize("status", ["completed", "archived"])
def test_invalid_destination_is_hidden_and_rejected(race_day, status):
    repository, _, source, destination, sarah, *_ = race_day
    add_athlete(repository, source, sarah.id, COACH)
    destination = repository.update_race(Race(**{**destination.__dict__, "status": status}))

    assert destination not in eligible_destination_races(repository, source)
    with pytest.raises(RepositoryError, match="no longer accept"):
        move_athlete(repository, source, destination, sarah.id, COACH)


def test_finalized_session_destination_is_rejected(race_day):
    repository, _, source, destination, sarah, *_ = race_day
    add_athlete(repository, source, sarah.id, COACH)
    repository.create_race_session(RaceSession(race_id=destination.id, status="completed", started_at=datetime.now(timezone.utc)))
    with pytest.raises(RepositoryError, match="no longer accept"):
        move_athlete(repository, source, destination, sarah.id, COACH)


@pytest.mark.parametrize("identity", [TIMER, None])
def test_timer_and_anonymous_accounts_cannot_mutate_rosters(race_day, identity):
    repository, _, source, _, sarah, *_ = race_day
    with pytest.raises(RepositoryError, match="Coach or administrator"):
        add_athlete(repository, source, sarah.id, identity)


@pytest.mark.parametrize("identity", [COACH, ADMIN])
def test_coach_and_admin_can_manage_rosters(race_day, identity):
    repository, _, source, _, sarah, *_ = race_day
    assert add_athlete(repository, source, sarah.id, identity).source_count == 1
