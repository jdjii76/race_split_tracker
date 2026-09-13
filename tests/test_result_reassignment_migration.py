from pathlib import Path


SQL = (Path(__file__).parents[1] / "supabase/migrations/034_result_reassignment.sql").read_text()


def test_reassignment_migration_is_append_only_and_authorized():
    lowered = SQL.lower()
    assert "create table if not exists public.result_reassignments" in lowered
    assert "require_app_role(array['coach','admin'])" in lowered
    assert "update public.split_events" not in lowered
    assert "delete from public.split_events" not in lowered
    assert "performed_by" in lowered and "reason" in lowered and "created_at" in lowered


def test_reassignment_rpc_checks_conflicts_and_adds_existing_permanent_athlete():
    lowered = SQL.lower()
    assert "destination athlete already has timing or result data" in lowered
    assert "insert into public.race_athletes" in lowered
    assert "select * into v_athlete from public.athletes" in lowered
    assert "insert into public.result_reassignments" in lowered
