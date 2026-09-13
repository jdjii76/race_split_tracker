"""Static additive/security contract for school sponsor migration 018."""
from pathlib import Path

PATH = Path("supabase/migrations/018_school_sponsors.sql")
SQL = PATH.read_text(encoding="utf-8").lower()


def test_migration_018_is_unique_additive_and_indexed():
    assert [item.name for item in PATH.parent.glob("018_*.sql")] == [PATH.name]
    assert "create table if not exists public.school_sponsors" in SQL
    assert "references public.school_profiles(id) on delete cascade" in SQL
    assert "display_order integer not null default 0 check (display_order >= 0)" in SQL
    assert SQL.count("create index if not exists idx_school_sponsors") == 4
    assert "delete from" not in SQL and "truncate " not in SQL


def test_sponsor_security_public_view_and_storage_contract():
    assert "alter table public.school_sponsors enable row level security" in SQL
    assert "public.has_app_role(array['admin'])" in SQL
    assert "revoke all on public.school_sponsors from anon" in SQL
    assert "create or replace view public.spectator_sponsors" in SQL
    assert "where ss.is_active" in SQL
    assert "grant select on public.spectator_sponsors to anon, authenticated" in SQL
    assert "insert into storage.buckets" in SQL and "'branding'" in SQL
    assert "public_read_branding_assets" in SQL and "admin_manage_branding_assets" in SQL
