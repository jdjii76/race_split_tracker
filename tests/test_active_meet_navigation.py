"""Tests for active-meet restoration and race-day actions."""
from dataclasses import replace
from split_tracker.models import Athlete
from split_tracker.navigation import (
    build_race_dashboard_summaries,
    dashboard_navigation_ids,
    determine_race_primary_action,
    get_meet_race_summaries,
    is_test_race,
    resolve_active_meet_id,
)
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession


def test_active_meet_is_restored_and_invalid_id_is_cleared():
    active = Meet(name="Championship", status="active")
    assert resolve_active_meet_id(active.id, [active]) == active.id
    assert resolve_active_meet_id("deleted", [Meet(name="Draft")]) is None


def test_only_relevant_meet_is_selected_automatically():
    upcoming = Meet(name="Saturday", status="upcoming")
    assert resolve_active_meet_id(None, [Meet(name="Draft"), upcoming]) == upcoming.id


def test_race_action_uses_session_status_as_source_of_truth():
    assert determine_race_primary_action("ready") == ("Open Race", "meet_setup")
    assert determine_race_primary_action("ready", "running") == ("Open Timing", "live_timing")
    assert determine_race_primary_action("running", "paused") == ("Open Timing", "live_timing")
    assert determine_race_primary_action("running", "completed") == ("View Results", "results")
    assert determine_race_primary_action("running", "awaiting_review") == ("Review Results", "results")


def test_dashboard_summaries_change_with_meet_and_handle_empty_meet():
    repo = InMemoryRaceRepository()
    first = repo.create_meet(Meet(name="First", status="active"))
    second = repo.create_meet(Meet(name="Second", status="upcoming"))
    race = repo.create_race(Race(meet_id=first.id, name="Varsity", distance_meters=5000, status="ready"))
    repo.replace_race_athletes(race.id, [Athlete(name="Alex")])
    session = repo.create_race_session(RaceSession(race_id=race.id))
    repo.update_race_session(replace(session, status="running"))

    first_rows, errors = get_meet_race_summaries(repo, first.id)
    second_rows, second_errors = get_meet_race_summaries(repo, second.id)

    assert not errors and not second_errors
    assert len(first_rows) == 1
    assert first_rows[0].athlete_count == 1
    assert first_rows[0].action_label == "Open Timing"
    assert first_rows[0].category == "running"
    assert second_rows == []


def test_dashboard_classifies_not_started_running_and_finished():
    meet_id = "meet"
    upcoming = Race(id="up-next", meet_id=meet_id, name="JV", distance_meters=5000, status="ready")
    running = Race(id="running", meet_id=meet_id, name="Varsity", distance_meters=5000, status="ready")
    finished = Race(id="finished", meet_id=meet_id, name="Open", distance_meters=5000, status="ready")
    sessions = [
        RaceSession(id="run-session", race_id=running.id, status="running"),
        RaceSession(id="finish-session", race_id=finished.id, status="completed"),
    ]

    summaries = build_race_dashboard_summaries(
        [upcoming, running, finished], sessions, {upcoming.id: 4, running.id: 5, finished.id: 6}
    )

    assert [item.category for item in summaries] == ["up_next", "running", "completed"]
    assert [item.display_status for item in summaries] == ["Not Started", "Running", "Finished"]
    assert [item.athlete_count for item in summaries] == [4, 5, 6]


def test_dashboard_classifies_timing_complete_as_awaiting_review():
    race = Race(id="review-race", meet_id="meet", name="Open", distance_meters=5000)
    session = RaceSession(id="review-session", race_id=race.id, status="awaiting_review")

    summary = build_race_dashboard_summaries([race], [session], {})[0]

    assert summary.category == "awaiting_review"
    assert summary.display_status == "Awaiting Review"
    assert summary.action_label == "Review Results"


def test_multiple_running_races_and_sessions_remain_isolated_by_race_uuid():
    first = Race(id="race-a", meet_id="meet", name="Same Name", distance_meters=5000)
    second = Race(id="race-b", meet_id="meet", name="Same Name", distance_meters=5000)
    sessions = [
        RaceSession(id="session-b", race_id=second.id, status="running"),
        RaceSession(id="old-a", race_id=first.id, status="completed"),
        RaceSession(id="session-a", race_id=first.id, status="running"),
    ]

    summaries = build_race_dashboard_summaries([first, second], sessions, {})

    assert all(item.category == "running" for item in summaries)
    assert dashboard_navigation_ids(summaries[0]) == ("race-a", "session-a")
    assert dashboard_navigation_ids(summaries[1]) == ("race-b", "session-b")


def test_one_race_status_cannot_mark_another_race_running():
    first = Race(id="race-a", meet_id="meet", name="A", distance_meters=5000)
    second = Race(id="race-b", meet_id="meet", name="B", distance_meters=5000)
    running = RaceSession(id="session-a", race_id=first.id, status="running")

    summaries = build_race_dashboard_summaries([first, second], [running], {})

    assert summaries[0].category == "running"
    assert summaries[1].category == "up_next"
    assert summaries[1].session is None


def test_test_indicator_is_display_only_and_case_insensitive():
    assert is_test_race("TEST - Coach") is True
    assert is_test_race("  test - Manager 1") is True
    assert is_test_race("Boys TEST Varsity") is False


def test_dashboard_uses_batched_repository_operations():
    class TrackingRepository(InMemoryRaceRepository):
        def __init__(self):
            super().__init__()
            self.session_batch_calls = 0
            self.count_batch_calls = 0

        def list_race_sessions_for_races(self, race_ids):
            self.session_batch_calls += 1
            return super().list_race_sessions_for_races(race_ids)

        def count_race_athletes_for_races(self, race_ids):
            self.count_batch_calls += 1
            return super().count_race_athletes_for_races(race_ids)

        def list_race_athletes(self, *args, **kwargs):
            raise AssertionError("dashboard must not issue per-race roster queries")

        def get_active_or_latest_race_session_for_race(self, *args, **kwargs):
            raise AssertionError("dashboard must not issue per-race session queries")

    repo = TrackingRepository()
    meet = repo.create_meet(Meet(name="Invite"))
    repo.create_race(Race(meet_id=meet.id, name="A", distance_meters=5000))
    repo.create_race(Race(meet_id=meet.id, name="B", distance_meters=5000))

    summaries, errors = get_meet_race_summaries(repo, meet.id)

    assert len(summaries) == 2 and errors == []
    assert repo.session_batch_calls == repo.count_batch_calls == 1
