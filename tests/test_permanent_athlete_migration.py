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


def test_branding_precedes_permanent_athletes_and_has_application_fields():
    migration_dir = MIGRATION.parent
    branding = (migration_dir / "008_school_branding.sql").read_text(encoding="utf-8").lower()
    expected_fields = (
        "school_name", "short_name", "program_name", "mascot", "city", "state",
        "app_title", "primary_color", "secondary_color", "accent_color",
        "text_on_primary", "logo_path", "compact_logo_path", "header_style",
        "show_logo_on_dashboard", "show_logo_on_timing",
        "include_branding_on_exports",
    )
    assert all(field in branding for field in expected_fields)
    assert (migration_dir / "008_school_branding.sql").name < MIGRATION.name


def test_reference_schemas_declare_canonical_migration_authority():
    root = MIGRATION.parents[2]
    development_schema = (root / "supabase/sql/development_schema.sql").read_text(encoding="utf-8").lower()
    legacy_schema = (root / "database/migrations/001_initial_schema.sql").read_text(encoding="utf-8").lower()
    readme = " ".join((root / "README.md").read_text(encoding="utf-8").lower().split())
    assert "not authoritative" in development_schema
    assert "legacy reference copy only" in legacy_schema
    assert "only authoritative production schema history" in readme


def test_repository_health_check_includes_permanent_athletes_table():
    source = (MIGRATION.parents[2] / "split_tracker/repository.py").read_text(encoding="utf-8")
    assert '("athletes", "id")' in source
