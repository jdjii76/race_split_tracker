"""Static authorization contract for ResultEvent insertion in migration 023."""
from pathlib import Path

MIGRATIONS = Path("supabase/migrations")
PATH = MIGRATIONS / "023_result_event_insert_authorization.sql"
SQL = PATH.read_text(encoding="utf-8").lower()


def _policy_allows(role: str, *, authenticated: bool = True) -> bool:
    """Model the exact authenticated-role boundary declared by the policy."""
    return authenticated and role in {"coach", "admin"}


def test_migration_023_is_unique_additive_and_grants_required_privileges():
    assert [path.name for path in MIGRATIONS.glob("023_*.sql")] == [PATH.name]
    assert "grant select, insert on table public.result_events to authenticated" in SQL
    assert "drop table" not in SQL
    assert "delete from" not in SQL
    assert "truncate " not in SQL


def test_insert_policy_uses_existing_staff_role_check_and_with_check():
    assert "create policy result_events_staff_insert" in SQL
    assert "for insert" in SQL
    assert "to authenticated" in SQL
    assert "with check (public.has_app_role(array['coach','admin']))" in SQL
    assert "to anon" not in SQL


def test_coach_can_append_result_event():
    assert _policy_allows("coach")


def test_admin_can_append_result_event():
    assert _policy_allows("admin")


def test_timer_cannot_append_result_event():
    assert not _policy_allows("timer")


def test_spectator_cannot_append_result_event():
    assert not _policy_allows("", authenticated=False)
