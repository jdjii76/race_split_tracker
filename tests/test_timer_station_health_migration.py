from pathlib import Path


SQL = (Path(__file__).resolve().parents[1] / "supabase/migrations/032_timer_station_health.sql").read_text().lower()


def test_station_health_uses_minimal_locked_down_heartbeat_table():
    assert "create table if not exists public.timer_station_status" in SQL
    assert "alter table public.timer_station_status enable row level security" in SQL
    assert "revoke all on public.timer_station_status from public, anon, authenticated" in SQL
    assert "create policy" not in SQL


def test_timer_heartbeat_is_security_definer_and_exactly_assignment_scoped():
    heartbeat = SQL[SQL.index("create or replace function public.heartbeat_timer_station"):SQL.index("create or replace function public.list_timer_station_health")]
    assert "security definer" in heartbeat
    assert "require_app_role(array['timer'])" in heartbeat
    assert "user_id=auth.uid()" in heartbeat
    assert "checkpoint_number=p_checkpoint_number" in heartbeat
    assert "device_id=trim(p_device_id)" in heartbeat
    assert "update public.race_sessions" not in heartbeat


def test_coach_monitor_is_role_checked_and_derives_capture_data_from_events():
    monitor = SQL[SQL.index("create or replace function public.list_timer_station_health"):]
    assert "require_app_role(array['coach','admin'])" in monitor
    assert "from public.split_events" in monitor
    assert "capture_mode='pack'" in monitor
    assert "where st.race_session_id=p_session_id" in monitor
    assert "grant execute on function public.list_timer_station_health(uuid) to authenticated" in monitor

