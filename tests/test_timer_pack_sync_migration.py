"""Security regression checks for timer Pack Mode synchronization."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK_RPC = (ROOT / "supabase/migrations/020_pack_timing_mode.sql").read_text(
    encoding="utf-8"
).lower()
TIMER_ROLE = (ROOT / "supabase/migrations/024_race_day_timer_role.sql").read_text(
    encoding="utf-8"
).lower()
PACK_SYNC = (ROOT / "supabase/migrations/026_timer_pack_sync.sql").read_text(
    encoding="utf-8"
).lower()


def test_timer_pack_rpc_uses_validated_security_definer_path():
    assert "record_pack_split_events(uuid, jsonb, text)" in PACK_SYNC
    assert "security definer" in PACK_SYNC
    assert "require_app_role(array['coach','admin'])" in PACK_RPC
    assert "public.has_app_role(array['timer'])" in TIMER_ROLE


def test_coach_and_admin_keep_existing_pack_rpc_authorization():
    assert "require_app_role(array['coach','admin'])" in PACK_RPC
    assert "public.has_app_role(p_roles)" in TIMER_ROLE


def test_pack_rpc_preserves_checkpoint_athlete_and_append_only_validation():
    assert "invalid athlete for this race session" in PACK_RPC
    assert "invalid checkpoint for this race session" in PACK_RPC
    assert "pack event session mismatch" in PACK_RPC
    assert "insert into public.split_events" in PACK_RPC
    assert "pack_conflict" in PACK_RPC
    assert "update public.split_events" not in PACK_RPC
    assert "delete from public.split_events" not in PACK_RPC


def test_unauthorized_users_remain_blocked_by_application_role_guard():
    assert "require_app_role(array['coach','admin'])" in PACK_RPC
    assert "auth.uid() is null" in TIMER_ROLE
    assert "raise exception 'not authorized'" in TIMER_ROLE


def test_timer_has_no_direct_race_session_write_policy():
    assert "app_timer_sessions_read" in TIMER_ROLE
    assert "on public.race_sessions for select" in TIMER_ROLE
    assert "app_timer_sessions_write" not in TIMER_ROLE
    assert "on public.race_sessions for update" not in TIMER_ROLE
    assert "create policy" not in PACK_SYNC
    assert "grant update" not in PACK_SYNC
