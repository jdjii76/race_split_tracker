"""Static contract tests for the deployable permanent-roster migration."""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/009_permanent_athletes.sql"


def test_permanent_roster_migration_has_expected_schema_and_safe_linkage():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "create table if not exists public.athletes" in sql
    for column in ("school_profile_id uuid", "first_name text", "last_name text", "preferred_name text", "graduation_year integer", "gender text", "team_division text", "status text", "athlete_number text", "notes text", "created_at timestamptz", "updated_at timestamptz"):
        assert column in sql
    assert "references public.school_profiles(id) on delete restrict" in sql
    assert "add column if not exists athlete_id uuid null" in sql
    assert "references public.athletes(id) on delete restrict" in sql
    assert "rename column athlete_id to legacy_athlete_id" in sql
    assert "update public.race_athletes" not in sql
    assert "alter table public.athletes enable row level security" in sql
    assert "create policy dev_anon_all_athletes" in sql
    assert "grant select, insert, update, delete on table public.athletes to anon" in sql


def test_migration_versions_are_unique_and_concerns_are_separate():
    migration_dir = MIGRATION.parent
    migrations = sorted(migration_dir.glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in migrations]
    assert len(versions) == len(set(versions))
    assert (migration_dir / "008_school_branding.sql").exists()
    assert not (migration_dir / "008_permanent_athlete_roster.sql").exists()


def test_repository_health_check_includes_permanent_athletes_table():
    source = (MIGRATION.parents[2] / "split_tracker/repository.py").read_text(encoding="utf-8")
    assert '("athletes", "id")' in source
