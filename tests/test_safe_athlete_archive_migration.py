"""Contracts for forward-only safe athlete archive migration 014."""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/014_safe_athlete_archive.sql"


def test_archive_migration_extends_status_and_guards_deletion_by_uuid():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "'archived'" in sql
    assert "delete_unused_athlete(p_athlete_id uuid)" in sql
    assert "race_athletes where athlete_id = p_athlete_id" in sql
    assert "for update" in sql
    assert "delete from public.athletes where id = p_athlete_id" in sql
    assert "delete from public.race_athletes" not in sql
    assert "delete from public.split_events" not in sql


def test_archive_migration_is_next_unique_version():
    migrations = sorted(MIGRATION.parent.glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in migrations]
    assert len(versions) == len(set(versions))
    assert MIGRATION in migrations
