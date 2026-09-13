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


def test_duplicate_names_remain_distinct_and_clear_before_timing():
    repo, race = setup_repository()
    first = repo.create_athlete(PermanentAthlete(first_name="Jordan", last_name="Lee"))
    second = repo.create_athlete(PermanentAthlete(first_name="Jordan", last_name="Lee"))

    selected = repo.replace_race_athletes_from_roster(race.id, [first.id, second.id])
    cleared = repo.replace_race_athletes_from_roster(race.id, [])

    assert len({item.athlete_id for item in selected}) == 2
    assert cleared == []


def test_deactivated_permanent_athlete_retains_historical_race_snapshot():
    repo, race = setup_repository()
    athlete = repo.create_athlete(PermanentAthlete(first_name="Alex", last_name="Smith"))
    snapshot = repo.replace_race_athletes_from_roster(race.id, [athlete.id])[0]

    repo.set_athlete_status(athlete.id, "inactive")

    restored = repo.list_race_athletes(race.id, include_inactive=True)[0]
    assert restored.athlete_id == athlete.id
    assert restored.name == snapshot.name == "Alex Smith"


def test_delete_unused_athlete_removes_only_that_uuid():
    repo, _ = setup_repository()
    duplicate = repo.create_athlete(PermanentAthlete(first_name="Jordan", last_name="Lee"))
    keeper = repo.create_athlete(PermanentAthlete(first_name="Jordan", last_name="Lee"))

    assert repo.athlete_has_race_history(duplicate.id) is False
    assert repo.delete_unused_athlete(duplicate.id) is True
    assert repo.get_athlete(duplicate.id) is None
    assert repo.get_athlete(keeper.id) == keeper


def test_delete_athlete_with_history_is_rejected_without_changing_history():
    repo, race = setup_repository()
    athlete = repo.create_athlete(PermanentAthlete(first_name="Jordan", last_name="Smith"))
    snapshot = repo.replace_race_athletes_from_roster(race.id, [athlete.id])[0]

    assert repo.athlete_has_race_history(athlete.id) is True
    with pytest.raises(RepositoryError, match="race history"):
        repo.delete_unused_athlete(athlete.id)

    assert repo.get_athlete(athlete.id) == athlete
    assert repo.list_race_athletes(race.id, include_inactive=True) == [snapshot]


def test_archive_restore_preserves_uuid_history_and_default_visibility():
    repo, race = setup_repository()
    athlete = repo.create_athlete(PermanentAthlete(first_name="Jordan", last_name="Smith"))
    snapshot = repo.replace_race_athletes_from_roster(race.id, [athlete.id])[0]

    archived = repo.archive_athlete(athlete.id)
    assert archived.id == athlete.id
    assert repo.get_athlete(athlete.id) == archived
    assert repo.list_athletes() == []
    assert repo.list_athletes(include_archived=True) == [archived]
    assert repo.list_race_athletes(race.id, include_inactive=True) == [snapshot]

    restored = repo.restore_athlete(athlete.id)
    assert restored.id == athlete.id and restored.status == "active"
    assert repo.list_athletes() == [restored]
    assert repo.list_race_athletes(race.id, include_inactive=True) == [snapshot]


def test_archived_athlete_stays_on_existing_race_but_cannot_join_another():
    repo, existing_race = setup_repository()
    athlete = repo.create_athlete(PermanentAthlete(first_name="Jordan", last_name="Smith"))
    repo.replace_race_athletes_from_roster(existing_race.id, [athlete.id])
    repo.archive_athlete(athlete.id)
    another_race = repo.create_race(Race(meet_id=existing_race.meet_id, name="JV", distance_meters=5000))

    assert repo.list_race_athlete_ids(existing_race.id) == [athlete.id]
    with pytest.raises(RepositoryError, match="Archived athletes"):
        repo.replace_race_athletes_from_roster(another_race.id, [athlete.id])
    assert repo.list_race_athlete_ids(another_race.id) == []
