"""Static contract for migration 017's database authorization boundary."""
from pathlib import Path

MIGRATIONS = Path("supabase/migrations")
PATH = MIGRATIONS / "017_secure_coach_and_spectator_access.sql"
SQL = PATH.read_text(encoding="utf-8").lower()


def test_migration_017_is_unique_and_forward_only():
    assert PATH.exists()
    assert [p.name for p in MIGRATIONS.glob("017_*.sql")] == [PATH.name]
    assert "delete from public.split_events" not in SQL
    assert "delete from public.race_sessions" not in SQL
    assert "truncate " not in SQL


def test_anon_mutations_are_revoked_and_public_reads_are_views_only():
    assert "revoke execute on all functions in schema public from public, anon" in SQL
    assert "revoke all on public.meets" in SQL
    assert "grant select on public.spectator_meets" in SQL
    assert "grant select on public.school_profiles to anon" in SQL
    for function in ("record_shared_split", "invalidate_split_event", "record_manual_split", "set_race_athlete_dnf", "clear_race_athlete_dnf", "finalize_race_session", "reopen_race_session", "transition_race_session", "get_or_create_active_race_session", "delete_unused_athlete"):
        assert f"grant execute on function public.{function}" in SQL
        assert f"grant execute on function public.{function}" not in "\n".join(
            line for line in SQL.splitlines() if " to anon" in line
        )
    assert "for all to anon" not in SQL


def test_roles_rls_and_rpc_defense_in_depth_exist():
    assert "create table if not exists public.app_users" in SQL
    assert "alter table public.app_users enable row level security" in SQL
    assert "auth.uid()" in SQL and "public.has_app_role" in SQL
    assert SQL.count("perform public.require_app_role") == 11
    for function in ("record_shared_split", "invalidate_split_event", "record_manual_split", "set_race_athlete_dnf", "clear_race_athlete_dnf", "finalize_race_session", "reopen_race_session", "transition_race_session", "get_or_create_active_race_session", "delete_unused_athlete"):
        assert f"grant execute on function public.{function}" in SQL
    assert "public.delete_unused_athlete" in SQL and "array['admin']" in SQL


def test_public_views_exclude_private_fields():
    roster = SQL.split("create or replace view public.spectator_roster", 1)[1].split("create or replace view", 1)[0]
    events = SQL.split("create or replace view public.spectator_split_events", 1)[1].split("create or replace view", 1)[0]
    assert "notes" not in roster and "target_finish" not in roster and "bib_number" not in roster
    assert "recorded_by" not in events and "corrected_by" not in events
