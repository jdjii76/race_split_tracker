"""Race Day presentation state and workflow guard tests."""
from pathlib import Path

from split_tracker.timer_mode import timing_readiness, timing_sync_label


def test_readiness_uses_existing_queue_connection_and_device_signals():
    ready = timing_readiness({"pack_device_id": "device-1", "storage_connected": True,
                              "pack_unsynced_count": 0}, repository_available=True)
    assert ready.overall == "READY"
    assert ready.network == "ONLINE" and ready.local_queue == "READY"
    assert ready.device == "READY" and ready.server == "READY"
    assert timing_sync_label({"repository": object(), "pack_device_id": "d",
                              "storage_connected": True}) == "ONLINE • 0 QUEUED"


def test_offline_readiness_preserves_durable_local_queue_and_count():
    state = {"repository": object(), "pack_device_id": "device-1",
             "pack_sync_error": "network", "pack_unsynced_count": 4}
    readiness = timing_readiness(state, repository_available=True)
    assert readiness.overall == "READY"
    assert readiness.network == "OFFLINE" and readiness.queued_count == 4
    assert timing_sync_label(state) == "OFFLINE • 4 SAVED LOCALLY"


def test_missing_device_is_attention_without_inventing_queue_state():
    readiness = timing_readiness({}, repository_available=False)
    assert readiness.overall == "ATTENTION"
    assert readiness.device == readiness.server == "ATTENTION"
    assert readiness.queued_count == 0


def test_race_day_landing_has_four_primary_workspaces_and_recovery():
    source = Path("pages/meet_dashboard.py").read_text()
    for label in ("Time a Checkpoint", "Finish Line", "Coach Dashboard", "Spectator View"):
        assert label in source
    assert "Current Meet" in source and "Recover Timing Data" in source


def test_station_selection_has_readiness_and_explicit_lock_confirmation():
    source = Path("pages/race_day_timer.py").read_text()
    for label in ("Ready to Time?", "Network", "Server", "Local queue", "Device"):
        assert label in source
    assert "Lock Station & Open Timing" in source
    assert "Change Locked Station" in source and "Unlock Station" in source
    assert "change_timing_station(st.session_state)" in source


def test_live_timing_has_persistent_locked_header_sync_strip_and_recovery():
    source = Path("pages/live_timing.py").read_text()
    assert "position: sticky" in source
    assert "LOCKED" in source and "timing_sync_label(st.session_state)" in source
    assert "Change Locked Station" in source and "Unlock & Change" in source
    assert "Recover Timing Data" in source and "pack_unsynced_count" in source


def test_existing_browser_queue_reports_status_without_changing_its_storage_format():
    source = Path("split_tracker/pack_component/frontend/index.html").read_text()
    assert "online:navigator.onLine" in source
    assert "queued_count:" in source and "synced_count:" in source
    assert "kmhs:pack:" in source and "localStorage" in source
