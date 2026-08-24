"""The checkpoint lookup index must support append-only correction rows."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (
    ROOT / "supabase/migrations/031_append_only_checkpoint_index.sql"
).read_text(encoding="utf-8").lower()
PACK_SQL = (
    ROOT / "supabase/migrations/020_pack_timing_mode.sql"
).read_text(encoding="utf-8").lower()
CORRECTION_SQL = (
    ROOT / "supabase/migrations/019_append_only_timing_corrections.sql"
).read_text(encoding="utf-8").lower()


def test_legacy_unique_checkpoint_index_is_replaced_by_non_unique_lookup():
    assert "drop index if exists public.split_events_one_active_checkpoint" in SQL
    assert "create index if not exists idx_split_events_session_athlete_checkpoint_lookup" in SQL
    assert "on public.split_events (race_session_id, athlete_id, checkpoint_number)" in SQL
    assert "create unique index" not in SQL


def test_other_event_id_and_void_target_uniqueness_remain_untouched():
    assert "idx_split_events_client_event_id" in PACK_SQL
    assert "unique index" in PACK_SQL
    assert "idx_split_events_one_void_per_target" in CORRECTION_SQL
    assert "unique index" in CORRECTION_SQL
    assert "idx_split_events_client_event_id" not in SQL
    assert "idx_split_events_one_void_per_target" not in SQL


def test_index_migration_does_not_change_authorization_or_event_rows():
    assert "function" not in SQL
    assert "grant " not in SQL
    assert "update public.split_events" not in SQL
    assert "delete from public.split_events" not in SQL
