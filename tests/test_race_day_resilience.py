from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from split_tracker.race_day_resilience import (
    connection_label,
    deterministic_pending_events,
    finalization_risks,
)


def test_pending_events_are_deduplicated_and_retried_in_device_sequence():
    events = [
        {"client_event_id": "two", "race_session_id": "race", "device_id": "b", "capture_sequence": 2, "captured_at": "2026-01-01T00:00:02Z", "state": "failed"},
        {"client_event_id": "one", "race_session_id": "race", "device_id": "b", "capture_sequence": 1, "captured_at": "2026-01-01T00:00:01Z", "state": "pending"},
        {"client_event_id": "one", "race_session_id": "race", "device_id": "b", "capture_sequence": 1, "captured_at": "2026-01-01T00:00:01Z", "state": "pending"},
        {"client_event_id": "done", "race_session_id": "race", "state": "synced"},
        {"client_event_id": "other", "race_session_id": "other", "state": "pending"},
    ]
    assert [event["client_event_id"] for event in deterministic_pending_events(events, "race")] == ["one", "two"]


def test_connection_state_uses_server_failures_as_well_as_browser_signal():
    assert connection_label(browser_online=False, pending_count=7) == ("offline", "Offline · 7 saved on this device")
    assert connection_label(browser_online=True, pending_count=5, consecutive_failures=2) == ("degraded", "Connection problem · 5 saved on this device")
    assert connection_label(browser_online=True, pending_count=4, syncing=True) == ("syncing", "Online · Syncing 4")
    assert connection_label(browser_online=True, pending_count=0) == ("online", "Online · All synced")


def test_finalization_warning_is_precise_about_unknown_offline_queue():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    station = SimpleNamespace(
        checkpoint_label="Mile 2", last_seen=now - timedelta(minutes=4),
        pending_sync_count=None, client_connection_state="offline",
    )
    risks = finalization_risks([station], local_pending=2, now=now)
    assert risks[0].checkpoint_label == "This device"
    assert risks[1].state == "offline"
    assert "pending count unknown" in risks[1].detail
    assert "may contain unsynchronized" in risks[1].detail

def test_browser_store_preserves_queues_for_other_races():
    source = open("split_tracker/pack_component/frontend/index.html", encoding="utf-8").read()
    persist = source.split("function persist()", 1)[1].split("function restoreQueue()", 1)[0]
    assert "race_session_id!==args.race_session_id" in persist
    assert "events:[...unique.values()]" in persist
