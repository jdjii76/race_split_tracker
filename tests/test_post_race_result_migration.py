from pathlib import Path

SQL = Path('supabase/migrations/022_post_race_result_events.sql').read_text()

def test_post_race_migration_is_append_only_and_role_guarded():
    lowered=SQL.lower()
    assert 'create table if not exists public.result_events' in lowered
    assert "require_app_role(array['coach','admin'])" in lowered
    assert 'status<>\'completed\'' in lowered
    assert 'supersedes_id' in lowered and 'result_events_one_successor' in lowered
    assert 'drop table' not in lowered and 'delete from' not in lowered

def test_public_function_only_returns_chain_heads_without_audit_metadata():
    assert 'get_public_result_events' in SQL
    assert 'not exists(select 1 from public.result_events n where n.supersedes_id=e.id)' in SQL
    assert 'null::text,null::uuid,null::uuid' in SQL
