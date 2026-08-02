"""Permanent athlete CSV parsing, duplicate review, and confirmed import tests."""
from split_tracker.athlete_import import CSV_COLUMNS, csv_template_bytes, import_athlete_rows, parse_athlete_csv
from split_tracker.models import PermanentAthlete
from split_tracker.repository import InMemoryRaceRepository


def test_template_has_documented_columns():
    assert csv_template_bytes().decode().strip() == ",".join(CSV_COLUMNS)


def test_parse_valid_csv_without_writing_repository():
    repo = InMemoryRaceRepository()
    rows = parse_athlete_csv(
        b"first_name,last_name,preferred_name,graduation_year,gender,team_division,athlete_number,status,notes\n Alex , Smith ,Lex,2027,F,Varsity,42,active, Captain \n",
        repo.list_athletes(),
    )
    assert repo.list_athletes() == []
    assert not rows[0].errors
    assert rows[0].athlete.display_name == "Lex Smith"
    assert rows[0].athlete.graduation_year == 2027


def test_parse_reports_required_fields_year_status_and_in_file_duplicates():
    rows = parse_athlete_csv(
        b"first_name,last_name,graduation_year,athlete_number,status\n,Smith,2027,7,active\nAlex,Jones,2027.5,8,active\nBlake,Jones,2028,9,unknown\nCasey,Jones,2028,9,active\n"
    )
    assert all(row.errors for row in rows)
    assert "duplicated within this CSV" in rows[-1].errors[0]


def test_existing_duplicate_can_be_skipped_updated_or_created():
    existing = PermanentAthlete(first_name="Alex", last_name="Smith", athlete_number="42", notes="old")

    skip_repo = InMemoryRaceRepository()
    skip_repo.create_athlete(existing)
    rows = parse_athlete_csv(b"first_name,last_name,athlete_number,notes\nAlex,Smith,42,new\n", skip_repo.list_athletes())
    assert rows[0].duplicate_athlete_id == existing.id
    skipped = import_athlete_rows(skip_repo, rows, "skip")
    assert skipped.skipped == 1 and len(skip_repo.list_athletes()) == 1

    update_repo = InMemoryRaceRepository()
    update_repo.create_athlete(existing)
    updated = import_athlete_rows(update_repo, rows, "update")
    assert updated.updated == 1
    assert update_repo.get_athlete(existing.id).notes == "new"

    create_repo = InMemoryRaceRepository()
    create_repo.create_athlete(existing)
    created = import_athlete_rows(create_repo, rows, "create")
    assert created.created == 1 and len(create_repo.list_athletes()) == 2


def test_missing_columns_and_malformed_file_do_not_import():
    missing = parse_athlete_csv(b"preferred_name\nAlex\n")
    malformed = parse_athlete_csv(b'first_name,last_name\n"Alex,Smith\n')
    repo = InMemoryRaceRepository()
    assert missing[0].errors
    assert malformed[0].errors
    summary = import_athlete_rows(repo, missing + malformed, "skip")
    assert summary.failed == 2
    assert repo.list_athletes() == []
