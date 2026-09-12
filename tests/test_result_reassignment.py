"""Controlled append-only result reassignment tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from split_tracker.auth import AppIdentity
from split_tracker.models import Athlete, Checkpoint, PermanentAthlete
from split_tracker.progression import get_completed_results
from split_tracker.repository import (
    InMemoryRaceRepository, Meet, Race, RaceSession, RaceSessionCheckpoint,
    RepositoryError, ResultEvent, SplitEvent,
)
from split_tracker.result_reassignment import preview_reassignment, reassign_result
from split_tracker.results import reconstruct_results
from split_tracker.split_invalidation import remove_split_from_results


COACH = AppIdentity("coach-user", "coach@example.com", "coach")
ADMIN = AppIdentity("admin-user", "admin@example.com", "admin")
TIMER = AppIdentity("timer-user", "timer@example.com", "timer")


def performance_fixture():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="State Meet", season="2026"))
    race = repo.create_race(Race(meet_id=meet.id, name="Varsity 5K", distance_meters=5000))
    john = repo.create_athlete(PermanentAthlete(first_name="John", last_name="Smith", athlete_number="22"))
    michael = repo.create_athlete(PermanentAthlete(first_name="Michael", last_name="Jones", athlete_number="31"))
    repo.replace_race_athletes_from_roster(race.id, [john.id])
    started = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
    session = repo.create_race_session(RaceSession(race_id=race.id, status="completed", started_at=started, ended_at=started + timedelta(minutes=20)))
    checkpoints = [
        RaceSessionCheckpoint(session.id, 1, "Mile 1", 1609.344),
        RaceSessionCheckpoint(session.id, 2, "Finish", 5000, is_finish=True),
    ]
    for item in checkpoints:
        repo.race_session_checkpoints[(session.id, item.checkpoint_sequence)] = item
    captured = started + timedelta(minutes=6, seconds=12, milliseconds=400)
    split = repo.create_split_event(SplitEvent(
        race_session_id=session.id, athlete_id=john.id, athlete_name="John Smith", bib_number="22",
        checkpoint_number=1, checkpoint_label="Mile 1", elapsed_seconds=372.4, event_order=1,
        recorded_at=captured, captured_at=captured, device_id="finish-ipad", capture_sequence=17,
    ))
    finish = repo.create_split_event(SplitEvent(
        race_session_id=session.id, athlete_id=john.id, athlete_name="John Smith", bib_number="22",
        checkpoint_number=2, checkpoint_label="Finish", elapsed_seconds=1182.3, event_order=2,
        recorded_at=started + timedelta(seconds=1182.3), device_id="finish-ipad",
    ))
    result = repo.save_post_race_result(ResultEvent(
        session.id, john.id, "finished", "official", finish_seconds=1182.3,
        splits={1: 372.4}, note="Imported official finish", created_by="official-user",
    ))
    return repo, meet, race, session, john, michael, split, finish, result


def test_complete_reassignment_preserves_records_and_projects_destination():
    repo, _, race, session, john, michael, split, finish, result = performance_fixture()
    john_before, michael_before = repo.get_athlete(john.id), repo.get_athlete(michael.id)
    raw_before = repo.list_all_split_events(session.id)
    preview = preview_reassignment(repo, session.id, john.id, michael.id)

    audit = reassign_result(repo, session.id, john.id, michael.id, "Wrong athlete selected during race", COACH)

    assert preview.timing_event_count == 2 and preview.has_finish and preview.destination_will_be_added
    assert repo.get_athlete(john.id) == john_before
    assert repo.get_athlete(michael.id) == michael_before
    assert len(repo.athletes) == 2
    assert repo.list_race_athlete_ids(race.id) == [john.id, michael.id]
    projected = repo.list_active_split_events(session.id)
    assert [item.athlete_id for item in projected] == [michael.id, michael.id]
    assert [item.elapsed_seconds for item in projected] == [372.4, 1182.3]
    assert repo.list_all_split_events(session.id) == raw_before
    assert repo.list_all_split_events(session.id)[0].captured_at == split.captured_at
    assert repo.list_all_split_events(session.id)[0].device_id == "finish-ipad"
    assert repo.list_all_split_events(session.id)[0].capture_sequence == 17
    projected_results = repo.list_result_events(session.id)
    assert projected_results[0].athlete_id == michael.id
    assert projected_results[0].finish_seconds == result.finish_seconds
    assert audit.original_athlete_id == john.id
    assert audit.destination_athlete_id == michael.id
    assert audit.performed_by == COACH.user_id
    assert audit.reason == "Wrong athlete selected during race"
    assert audit.created_at is not None

    rows = reconstruct_results(
        meet_name="State Meet", race_name=race.name, session=session,
        athletes=repo.list_race_athletes(race.id, include_inactive=True),
        checkpoints=[Checkpoint(1, "Mile 1", 1609.344), Checkpoint(2, "Finish", 5000, True)],
        race_distance_meters=5000, events=projected,
        outcomes=repo.list_race_athlete_outcomes(session.id), result_events=projected_results,
    )
    by_id = {row["Athlete ID"]: row for row in rows}
    assert by_id[michael.id]["Finish Time Seconds"] == 1182.3
    assert by_id[michael.id]["Mile 1 Split"] == "6:12.40"
    assert by_id[michael.id]["Finish Split"] == "13:29.90"
    assert by_id[john.id]["Finish Time Seconds"] is None


def test_reassignment_is_session_specific_and_progression_uses_destination():
    repo, meet, race, session, john, michael, *_ = performance_fixture()
    other_race = repo.create_race(Race(meet_id=meet.id, name="Open 5K", distance_meters=5000))
    repo.replace_race_athletes_from_roster(other_race.id, [john.id])
    other = repo.create_race_session(RaceSession(race_id=other_race.id, status="completed", started_at=datetime.now(timezone.utc)))
    repo.race_session_checkpoints[(other.id, 1)] = RaceSessionCheckpoint(other.id, 1, "Finish", 5000, is_finish=True)
    repo.create_split_event(SplitEvent(other.id, john.id, 1, 1200, 1, checkpoint_label="Finish"))

    reassign_result(repo, session.id, john.id, michael.id, "Substitution", ADMIN)

    assert repo.list_active_split_events(other.id)[0].athlete_id == john.id
    michael_history = get_completed_results(repo, michael.id)
    john_history = get_completed_results(repo, john.id)
    assert [item.session_id for item in michael_history] == [session.id]
    assert other.id in [item.session_id for item in john_history]
    assert session.id not in [item.session_id for item in john_history if item.finish_seconds is not None]


def test_reassigned_destination_can_remove_canonical_checkpoint_split():
    repo, _, _, session, john, michael, *_ = performance_fixture()
    reassign_result(repo, session.id, john.id, michael.id, "Substitution", ADMIN)
    projected = repo.list_active_split_events(session.id)
    mile_one = next(event for event in projected if event.checkpoint_number == 1)

    remove_split_from_results(repo, mile_one, "Unofficial reassigned split", ADMIN)

    assert all(event.checkpoint_number != 1 for event in repo.list_active_split_events(session.id))
    original = next(event for event in repo.list_all_split_events(session.id) if event.id == mile_one.id)
    assert original.athlete_id == john.id and not original.is_deleted


def test_destination_conflict_is_rejected_without_partial_changes():
    repo, _, race, session, john, michael, *_ = performance_fixture()
    repo.replace_race_athletes_from_roster(race.id, [john.id, michael.id])
    repo.create_split_event(SplitEvent(session.id, michael.id, 1, 390, 3))
    with pytest.raises(RepositoryError, match="destination athlete already has"):
        reassign_result(repo, session.id, john.id, michael.id, "Wrong athlete", COACH)
    assert repo.list_result_reassignments(session.id) == []


@pytest.mark.parametrize("identity", [COACH, ADMIN])
def test_staff_can_reassign(identity):
    repo, _, _, session, john, michael, *_ = performance_fixture()
    assert reassign_result(repo, session.id, john.id, michael.id, "Correction", identity)


def test_timer_cannot_reassign():
    repo, _, _, session, john, michael, *_ = performance_fixture()
    with pytest.raises(RepositoryError, match="Coach or administrator"):
        reassign_result(repo, session.id, john.id, michael.id, "Correction", TIMER)


def test_original_athlete_can_be_marked_dns_after_reassignment():
    repo, _, _, session, john, michael, *_ = performance_fixture()
    reassign_result(repo, session.id, john.id, michael.id, "Substitution", COACH)
    dns = repo.save_post_race_result(ResultEvent(session.id, john.id, "dns", "manual", note="Confirmed DNS"))
    canonical = {item.athlete_id: item for item in repo.list_result_events(session.id)}
    assert canonical[john.id].id == dns.id and canonical[john.id].status == "dns"
    assert canonical[michael.id].status == "finished"
