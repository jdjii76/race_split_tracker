"""Permanent school roster and race-selection behavior."""
from dataclasses import replace
from datetime import datetime, timezone
import pytest
from split_tracker.athletes import grade_from_graduation_year
from split_tracker.models import PermanentAthlete
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, RepositoryError, _athlete_from_row


def setup_repository():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Invite"))
    race = repo.create_race(Race(meet_id=meet.id, name="Varsity", distance_meters=5000))
    return repo, race


def test_create_update_status_search_and_filter_preserve_id():
    repo, _ = setup_repository()
    athlete = repo.create_athlete(PermanentAthlete(first_name="  Alexandria ", last_name=" Smith ", preferred_name="Alex", graduation_year=2027, gender="F", team_division="Varsity"))
    assert athlete.display_name == "Alex Smith"
    updated = repo.update_athlete(replace(athlete, preferred_name="Lexi"))
    injured = repo.set_athlete_status(athlete.id, "injured")
    assert updated.id == athlete.id == injured.id
    assert repo.list_athletes(status="injured", graduation_year=2027, gender="F", team_division="Varsity", search="Lexi") == [injured]


def test_grade_calculation():
    assert grade_from_graduation_year(2026, 2026) == "12th"
    assert grade_from_graduation_year(2027, 2026) == "11th"
    assert grade_from_graduation_year(2023, 2026) == "Graduated"
    assert grade_from_graduation_year(2032, 2026) == "Future student"
    assert grade_from_graduation_year(None, 2026) == "—"


def test_race_selection_is_unique_preserves_snapshots_and_allows_safe_removal():
    repo, race = setup_repository()
    first = repo.create_athlete(PermanentAthlete(first_name="Alex", last_name="Smith"))
    second = repo.create_athlete(PermanentAthlete(first_name="Blake", last_name="Jones"))
    selected = repo.replace_race_athletes_from_roster(race.id, [first.id, second.id])
    unchanged = repo.replace_race_athletes_from_roster(race.id, [first.id, second.id])
    repo.update_athlete(replace(first, preferred_name="Lexi", status="graduated"))
    reduced = repo.replace_race_athletes_from_roster(race.id, [first.id])
    assert [item.athlete_id for item in selected] == [item.athlete_id for item in unchanged]
    assert reduced[0].name == "Alex Smith"  # race-time snapshot is unchanged
    assert repo.list_race_athlete_ids(race.id) == [first.id]
    with pytest.raises(RepositoryError, match="only be selected once"):
        repo.replace_race_athletes_from_roster(race.id, [first.id, first.id])


def test_unsafe_removal_is_blocked_after_timing_starts():
    repo, race = setup_repository()
    first = repo.create_athlete(PermanentAthlete(first_name="Alex", last_name="Smith"))
    second = repo.create_athlete(PermanentAthlete(first_name="Blake", last_name="Jones"))
    repo.replace_race_athletes_from_roster(race.id, [first.id, second.id])
    repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=datetime.now(timezone.utc)))
    with pytest.raises(RepositoryError, match="cannot be removed"):
        repo.replace_race_athletes_from_roster(race.id, [first.id])
    assert set(repo.list_race_athlete_ids(race.id)) == {first.id, second.id}


def test_legacy_race_athlete_without_permanent_link_remains_readable():
    legacy = _athlete_from_row({"id": "row", "legacy_athlete_id": "legacy-id", "name": "Historic Runner"})
    assert legacy.athlete_id == "legacy-id"
    assert legacy.name == "Historic Runner"
