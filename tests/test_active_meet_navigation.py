"""Tests for active-meet restoration and race-day actions."""
from dataclasses import replace
from split_tracker.models import Athlete
from split_tracker.navigation import determine_race_primary_action, get_meet_race_summaries, resolve_active_meet_id
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession


def test_active_meet_is_restored_and_invalid_id_is_cleared():
    active = Meet(name="Championship", status="active")
    assert resolve_active_meet_id(active.id, [active]) == active.id
    assert resolve_active_meet_id("deleted", [Meet(name="Draft")]) is None


def test_only_relevant_meet_is_selected_automatically():
    upcoming = Meet(name="Saturday", status="upcoming")
    assert resolve_active_meet_id(None, [Meet(name="Draft"), upcoming]) == upcoming.id


def test_race_action_uses_session_status_as_source_of_truth():
    assert determine_race_primary_action("ready") == ("Start Timing", "live_timing")
    assert determine_race_primary_action("ready", "running") == ("Resume Timing", "live_timing")
    assert determine_race_primary_action("running", "paused") == ("Resume Timing", "live_timing")
    assert determine_race_primary_action("running", "completed") == ("View Results", "results")


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
    assert first_rows[0].action_label == "Resume Timing"
    assert second_rows == []
