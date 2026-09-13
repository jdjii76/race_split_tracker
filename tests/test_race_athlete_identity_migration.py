"""Contract tests for permanent/legacy race-athlete identity reconciliation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase/migrations/010_fix_race_athlete_identity_nullability.sql"


def test_identity_columns_are_nullable_with_at_least_one_required():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "alter column athlete_id drop not null" in sql
    assert "alter column legacy_athlete_id drop not null" in sql
    assert "check (athlete_id is not null or legacy_athlete_id is not null)" in sql
    assert "validate constraint race_athletes_identity_required" in sql


def test_migration_preserves_rows_indexes_history_and_reloads_postgrest():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "race_athletes_race_permanent_unique" in sql
    assert "race_athletes_race_legacy_unique" in sql
    assert "notify pgrst, 'reload schema'" in sql
    assert "delete from" not in sql
    assert "update public.race_athletes" not in sql
    assert "split_events" not in sql


def test_repository_writes_one_identity_for_each_roster_type():
    source = (ROOT / "split_tracker/repository.py").read_text(encoding="utf-8")
    assert 'row["athlete_id"], row["legacy_athlete_id"] = permanent.id, None' in source
    assert '"legacy_athlete_id": athlete.athlete_id' in source
