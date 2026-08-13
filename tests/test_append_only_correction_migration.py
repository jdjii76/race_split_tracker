"""Static safety contracts for append-only correction migration 019."""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/019_append_only_timing_corrections.sql"


def test_append_only_correction_schema_and_atomic_rpcs():
    sql = MIGRATION.read_text().lower()
    for field in ("event_type", "target_event_id", "corrects_event_id", "reason"):
        assert f"add column if not exists {field}" in sql
    assert "idx_split_events_one_void_per_target" in sql
    assert "create or replace function public.correct_split_athlete" in sql
    assert "create or replace function public.invalidate_split_event" in sql
    assert "update public.split_events" not in sql
    assert "delete from public.split_events" not in sql


def test_spectator_view_exposes_correction_links_without_raw_event_ids():
    sql = MIGRATION.read_text().lower()
    assert "create or replace view public.spectator_split_events" in sql
    assert "md5(se.race_session_id::text || ':' || se.target_event_id::text)" in sql
