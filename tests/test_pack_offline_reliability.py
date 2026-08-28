"""Static safety checks for the deliberately small browser-owned offline queue."""
from pathlib import Path


FRONTEND = (
    Path(__file__).resolve().parents[1]
    / "split_tracker/pack_component/frontend/index.html"
).read_text(encoding="utf-8")


def test_offline_state_is_prominent_and_does_not_disable_capture():
    assert "OFFLINE — timing is continuing on this device." in FRONTEND
    assert "locally queued / unsynchronized captures" in FRONTEND
    assert "DO NOT REFRESH OR CLOSE THIS PAGE WHILE OFFLINE." in FRONTEND
    assert "offline=!navigator.onLine||Boolean(args.sync_error)" in FRONTEND
    assert "function capture(a)" in FRONTEND
    assert "navigator.onLine" not in FRONTEND.split("function capture(a)", 1)[1].split("function undo()", 1)[0]


def test_queue_is_persisted_before_sync_and_only_acknowledgement_marks_synced():
    capture = FRONTEND.split("function capture(a)", 1)[1].split("function undo()", 1)[0]
    acknowledgement = FRONTEND.split("addEventListener('message'", 1)[1]
    assert capture.index("queue.push(event)") < capture.index("persist()") < capture.index("emit()")
    assert "crypto.randomUUID()" in capture
    assert "if(ack.has(x.client_event_id))x.state='synced'" in acknowledgement
    assert "queue.filter(e=>['pending','failed'].includes(e.state))" in FRONTEND


def test_retry_recovery_sync_now_and_unload_warning_reuse_same_queue():
    assert "Connection restored — synchronizing..." in FRONTEND
    assert "Synchronized · ${pending} queued · ${synced} synchronized" in FRONTEND
    assert "emit('sync_now')" in FRONTEND
    assert "setInterval(retryQueued,3000)" in FRONTEND
    assert "emit('component_ready')" in FRONTEND
    assert "addEventListener('focus',retryQueued)" in FRONTEND
    assert "addEventListener('pageshow',retryQueued)" in FRONTEND
    assert "addEventListener('beforeunload'" in FRONTEND
    assert "queue.some(x=>['pending','failed'].includes(x.state))" in FRONTEND


def test_component_recreation_recovers_queue_across_device_id_change():
    restore = FRONTEND.split("function restoreQueue()", 1)[1].split("function resize()", 1)[0]
    assert "args.race_session_id" in restore
    assert "args.checkpoint_number" in restore
    assert "args.device_id" not in restore
    assert "merged.set(event.client_event_id,event)" in restore
    assert "persist()" in restore
    assert "if(source!==key)localStorage.removeItem(source)" in restore
    assert "restoreQueue()" in FRONTEND.split("addEventListener('message'", 1)[1]


def test_retry_does_not_depend_on_navigator_online_event():
    retry = FRONTEND.split("function retryQueued()", 1)[1].split("addEventListener('online'", 1)[0]
    assert "navigator.onLine" not in retry
    assert "emit('reconnect_retry')" in retry


def test_local_undo_cancels_before_emit_and_synced_undo_uses_correction_action():
    undo = FRONTEND.split("function undo()", 1)[1].split("function render()", 1)[0]
    assert "if(e.state==='synced')" in undo
    assert "emit('undo_synced:'+e.client_event_id)" in undo
    assert "e.state='cancelled'" in undo
    assert "queue.filter(e=>['pending','failed'].includes(e.state))" in FRONTEND


def test_component_receives_complete_preloaded_capture_context():
    live = (Path(__file__).resolve().parents[1] / "pages/live_timing.py").read_text()
    for value in (
        "race_session_id=session_id",
        "checkpoint_number=checkpoint_number",
        "athletes=athlete_rows",
        "device_id=st.session_state.pack_device_id",
        'sync_error=st.session_state.get("pack_sync_error", "")',
    ):
        assert value in live
