"""Live timing page."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
import streamlit as st
from split_tracker.branding import render_school_header

from split_tracker.formatting import format_distance, format_duration, parse_time_to_seconds
from split_tracker.projection import (
    athlete_matches_search,
    ordered_race_board_athletes,
    ordered_timing_athletes,
    partition_finished_athletes,
)
from split_tracker.timing_persistence import (
    persist_cancel,
    persist_completion,
    persist_timing_complete,
    persist_pause,
    persist_resume,
    persist_event_correction,
    persist_athlete_reassignment,
    persist_manual_correction,
    persist_reopen,
    poll_shared_timing,
    record_authoritative_split,
    restore_timing_state,
    start_and_synchronize_shared_timing,
)
from split_tracker.timing_recovery import active_events_for_athlete, latest_active_event, recent_timing_activity
from split_tracker.timer_mode import (
    change_timing_station, exit_race_day_timing_mode, is_race_day_timing_mode,
    is_timing_operator, station_label,
)
from split_tracker.pack_component import pack_capture
from split_tracker.pack_timing import expected_arrival_metadata, normalize_pack_batch, ordered_expected_arrival_states, pack_capture_allowed
from split_tracker.state import (
    elapsed_seconds,
    end_race,
    pause_race,
    reset_race,
    resume_race,
    setup_is_valid,
    start_race,
)

logger = logging.getLogger(__name__)

_BUTTON_CSS = """
<style>
div[data-testid="stButton"] > button {
    min-height: 3rem;
    font-size: 1.05rem;
    font-weight: 700;
    border-radius: 0.9rem;
    white-space: pre-wrap;
}
div[data-testid="stButton"] > button[kind="primary"] { min-height: 5rem; }
[data-testid="stMetricValue"] { font-size: 2.7rem; }
.sync-ok { color: #16803a; font-weight: 700; }
.sync-warn { color: #b26a00; font-weight: 700; }
.sync-error { color: #b42318; font-weight: 700; }
</style>
"""

STATUS_LABELS = {
    "not_started": "Ready",
    "running": "Running",
    "paused": "Paused",
    "ended": "Finished",
}


def _clock_metric() -> None:
    clock = st.session_state.race_clock
    st.metric(
        f"{STATUS_LABELS[clock.status].upper()} • Race Clock",
        format_duration(elapsed_seconds(clock)),
    )


def athlete_timing_button_key(
    race_session_id: str, athlete_id: str, checkpoint_number: int | None
) -> str:
    """Return a stable identity for one session/athlete/checkpoint button."""
    checkpoint_key = "complete" if checkpoint_number is None else str(checkpoint_number)
    return f"split:{race_session_id}:{athlete_id}:{checkpoint_key}"


def athlete_timing_button_disabled(
    *,
    shared_unavailable: bool,
    race_session_id: str | None,
    clock_status: str,
    timer_name: str,
    checkpoint_number: int | None,
    finished: bool,
    reopened: bool,
) -> bool:
    """Return whether an authoritative checkpoint button must be disabled."""
    return (
        shared_unavailable
        or not race_session_id
        or clock_status != "running"
        or not timer_name
        or checkpoint_number is None
        or (finished and not reopened)
    )


def _live_board_frame(filter_value: str, search_value: str = "") -> pd.DataFrame:
    rows = []
    projection = st.session_state.get("projected_race_state")
    ordered = ordered_race_board_athletes(projection) if projection else ()
    for place, athlete_state in enumerate(ordered, start=1):
        athlete = athlete_state.athlete
        latest = athlete_state.splits[-1] if athlete_state.splits else None
        finished = athlete_state.finished
        if filter_value == "Active" and finished:
            continue
        if filter_value == "Finished" and not finished:
            continue
        if not athlete_matches_search(athlete_state, search_value):
            continue
        rows.append(
            {
                "Place": place,
                "Athlete": athlete.name,
                "Bib": athlete.bib_number,
                "Checkpoint": latest.checkpoint_label if latest else "Not started",
                "Cumulative": (
                    format_duration(latest.cumulative_time_seconds) if latest else "—"
                ),
                "Latest split": (
                    format_duration(latest.segment_split_seconds) if latest else "—"
                ),
                "Status": (
                    "Finished" if finished else ("Racing" if latest else "Not started")
                ),
            }
        )
    return pd.DataFrame(rows)


def _sync_status() -> tuple[str, str]:
    """Return a compact race-day connection label and CSS class."""
    if st.session_state.get("sync_error"):
        return "● Connection problem", "sync-error"
    if st.session_state.get("active_race_session_id") and st.session_state.get(
        "storage_connected"
    ):
        return "● Synced", "sync-ok"
    return "● Updating", "sync-warn"


def _has_persisted_race() -> bool:
    result = st.session_state.get("repository_result")
    shared_storage = result is None or not result.is_temporary
    return bool(
        shared_storage
        and st.session_state.get("selected_race_id")
        and st.session_state.get("repository")
    )


def _show_persistence_error(operation: str, exc: Exception) -> None:
    logger.exception(
        "Live timing persistence failed",
        extra={
            "operation": operation,
            "race_id": st.session_state.get("selected_race_id"),
        },
    )
    st.error(
        f"{operation} could not be saved. The underlying error was logged; no Supabase secrets were displayed."
    )


def _restore_if_needed() -> None:
    race_id = st.session_state.get("selected_race_id")
    if not race_id or not st.session_state.get("repository"):
        return
    if st.session_state.get("timing_restored_for_race_id") == race_id:
        return
    try:
        restored = restore_timing_state(st.session_state)
        # Keep looking on subsequent fragment runs when another browser may
        # create the first session after this browser reached the waiting page.
        if restored is not None:
            st.session_state.timing_restored_for_race_id = race_id
    except Exception as exc:
        _show_persistence_error("Restore timing session", exc)


def _heartbeat_timer_station() -> None:
    """Refresh timer presence at most every 30 seconds."""
    if not (
        st.session_state.get("timer_mode")
        and st.session_state.get("active_race_session_id")
        and st.session_state.get("timer_station_checkpoint") is not None
        and st.session_state.get("pack_device_id")
    ):
        return
    now = datetime.now(timezone.utc)
    previous = st.session_state.get("timer_station_last_heartbeat_at")
    if previous is not None and (now - previous).total_seconds() < 30:
        return
    try:
        st.session_state.repository.heartbeat_timer_station(
            st.session_state.active_race_session_id,
            st.session_state.timer_station_checkpoint,
            st.session_state.pack_device_id,
        )
        st.session_state.timer_station_last_heartbeat_at = now
        st.session_state.timer_station_sync_status = "Connected"
    except Exception:
        logger.exception("Timer station heartbeat failed")
        st.session_state.timer_station_sync_status = "Connection problem"


def _start_timing() -> bool:
    try:
        if _has_persisted_race():
            start_and_synchronize_shared_timing(st.session_state)
            st.session_state.message = "Shared race started."
            return True
        return start_race(st.session_state)
    except Exception as exc:
        _show_persistence_error("Start race", exc)
        return False


def _pause_timing() -> bool:
    try:
        if _has_persisted_race():
            persist_pause(st.session_state)
        else:
            pause_race(st.session_state)
        return True
    except Exception as exc:
        _show_persistence_error("Pause race", exc)
        return False


def _resume_timing() -> bool:
    try:
        if _has_persisted_race():
            persist_resume(st.session_state)
        else:
            resume_race(st.session_state)
        return True
    except Exception as exc:
        _show_persistence_error("Resume race", exc)
        return False


def _end_timing() -> bool:
    try:
        if _has_persisted_race():
            persist_completion(st.session_state)
        else:
            end_race(st.session_state)
        return True
    except Exception as exc:
        _show_persistence_error("End race", exc)
        return False


def _reset_timing() -> bool:
    try:
        if _has_persisted_race() and st.session_state.get("active_race_session_id"):
            persist_cancel(st.session_state)
            st.session_state.active_race_session_id = None
            st.session_state.timing_restored_for_race_id = None
        reset_race(st.session_state)
        return True
    except Exception as exc:
        _show_persistence_error("Reset race", exc)
        return False


def _record_tap(athlete_id: str) -> bool:
    """Handle a click by revalidating and writing only authoritative state."""
    try:
        result = record_authoritative_split(st.session_state, athlete_id)
        st.session_state.message = result.message
        if result.status == "duplicate":
            st.warning(
                f"{result.message} Shared progress was reloaded; use the newly displayed next checkpoint."
            )
        else:
            # The widget interaction already causes a fragment rerun. Suppress
            # its normal poll so the RPC-returned event can render immediately.
            st.session_state.skip_next_live_poll = True
        return True
    except Exception as exc:
        _show_persistence_error("Record split", exc)
        st.session_state.message = (
            f"Split was not saved: {exc} Tap again after resolving the error."
        )
        return False


def _render_pack_mode(
    projection,
    clock,
    shared_unavailable: bool,
    station_number: int | None = None,
) -> bool:
    """Render the browser-owned rapid-capture surface; return whether it is active."""
    session_id = st.session_state.get("active_race_session_id")
    eligible = [state for state in (projection.athletes if projection else ()) if state.next_checkpoint and not state.finished and state.outcome_status != "dnf"]
    if station_number is not None:
        eligible = [
            state
            for state in eligible
            if state.next_checkpoint.number == station_number
        ]
    capture_allowed = pack_capture_allowed(
        session_id, clock.status, shared_unavailable, st.session_state.timer_name
    )
    st.markdown("### ⚡ PACK MODE")
    if not st.session_state.get("pack_mode_active"):
        st.caption("Rapid browser capture for runners arriving seconds apart. Normal timing remains available below.")
        if st.button("Enter Pack Mode", type="primary", use_container_width=True, disabled=not capture_allowed):
            st.session_state.pack_mode_active = True; st.rerun()
        return False
    if not capture_allowed:
        if station_number is not None and not shared_unavailable:
            if clock.status == "ended":
                st.info("Race timing is complete. Live capture is closed.")
                return True
            if not session_id or projection is None:
                st.info("Preparing the shared race session and athlete roster.")
                return True
            st.info("Pack Mode is prepared. Athlete capture unlocks when Finish Line starts the shared race clock.")
        else:
            st.error("Pack Mode stopped: the race/checkpoint context is no longer valid.")
            st.session_state.pack_mode_active = False
            return False
    if station_number is not None:
        checkpoint_number = station_number
    else:
        checkpoint_numbers = sorted({state.next_checkpoint.number for state in eligible})
        if not checkpoint_numbers:
            st.info("No athletes currently have a checkpoint available for Pack Mode.")
            return True
        checkpoint_number = st.selectbox("Current checkpoint", checkpoint_numbers, format_func=lambda n: next(cp.label for cp in st.session_state.meet_config.checkpoints if cp.number == n), key="pack_checkpoint")
    targets = [state for state in eligible if state.next_checkpoint.number == checkpoint_number]
    cp = next(cp for cp in st.session_state.meet_config.checkpoints if cp.number == checkpoint_number)
    if not targets:
        st.info(f"Waiting for runners to become eligible at {station_label(cp)}.")
    st.session_state.setdefault("pack_device_id", str(uuid4()))
    ack_ids = st.session_state.get("pack_ack_ids", [])
    athlete_rows=[]
    race_order={state.athlete.athlete_id:i for i,state in enumerate(ordered_race_board_athletes(projection))}
    display_states = projection.athletes if station_number is not None and projection else targets
    eligible_ids = {state.athlete.athlete_id for state in targets}
    arrival_metadata = expected_arrival_metadata(
        display_states,
        st.session_state.meet_config.checkpoints,
        checkpoint_number,
    )
    browser_states = ordered_expected_arrival_states(display_states, arrival_metadata)
    for state in browser_states:
        parts=state.athlete.name.strip().split(); athlete_rows.append({"id":state.athlete.athlete_id,"name":state.athlete.name,"first":" ".join(parts[:-1]),"last":parts[-1] if parts else state.athlete.name,"bib":state.athlete.bib_number,"team":state.athlete.team,"race":race_order[state.athlete.athlete_id],"eligible":capture_allowed and (state.athlete.athlete_id in eligible_ids or station_number is not None and not state.finished and state.outcome_status != "dnf"),**arrival_metadata[state.athlete.athlete_id]})
    value = pack_capture(race_session_id=session_id, checkpoint_number=checkpoint_number, checkpoint_label=station_label(cp),
        athletes=athlete_rows, device_id=st.session_state.pack_device_id, server_utc_ms=int(datetime.now(timezone.utc).timestamp()*1000), ack_ids=ack_ids, void_ids=st.session_state.get("pack_void_ids", []), key=f"pack:{session_id}:{checkpoint_number}")
    events = value.get("events", []) if isinstance(value, dict) else []
    action = value.get("action", "") if isinstance(value, dict) else ""
    if action.startswith("undo_synced:"):
        event_id=action.split(":",1)[1]; event=next((e for e in st.session_state.get("persisted_split_events",()) if (e.client_event_id or e.id)==event_id),None)
        if event and _correct_event(event):
            st.session_state.pack_void_ids=list({*st.session_state.get("pack_void_ids", []),event_id})
            st.rerun()
    if events:
        try:
            saved=normalize_pack_batch(st.session_state.repository,st.session_state.selected_race_id,session_id,checkpoint_number,events,st.session_state.timer_name)
            st.session_state.pack_ack_ids=list({*ack_ids,*(e.client_event_id or e.id for e in saved)})
            st.session_state.pack_last_sync_at=datetime.now(timezone.utc); st.session_state.pack_sync_error=""
            poll_shared_timing(st.session_state)
        except Exception as exc:
            st.session_state.pack_sync_error=str(exc)
    if st.session_state.get("pack_sync_error"): st.warning(f"OFFLINE / synchronization delayed — events remain in browser storage. {st.session_state.pack_sync_error}")
    left,right=st.columns(2)
    if left.button("Retry synchronization",use_container_width=True): st.rerun()
    if right.button("Switch to Individual Timing" if station_number is not None else "Exit Pack Mode",use_container_width=True):
        if events: st.warning(f"{len(events)} captured splits are still waiting to synchronize. Exit preserves the durable browser queue.")
        else:
            st.session_state.pack_mode_active=False
            if station_number is not None: st.session_state.timer_timing_mode="individual"
            st.rerun()
    if st.session_state.get("debug_mode"):
        with st.expander("Pack diagnostics"): st.json({"device_id":st.session_state.pack_device_id,"submitted":len(events),"acknowledged":len(st.session_state.get("pack_ack_ids",[])),"latest_sync":str(st.session_state.get("pack_last_sync_at")),"sync_error":st.session_state.get("pack_sync_error","")})
    return True


def _correct_event(event, *, require_latest: bool = False) -> bool:
    try:
        persist_event_correction(st.session_state, event, require_latest=require_latest)
        st.session_state.message = f"Corrected {event.athlete_name} at {event.checkpoint_label}."
        st.session_state.recovery_mode = ""
        return True
    except Exception as exc:
        _show_persistence_error("Correct split", exc)
        st.error(str(exc))
        return False


def _add_missed_split(athlete_id: str, checkpoint_number: int, elapsed_seconds: float) -> bool:
    try:
        event = persist_manual_correction(st.session_state, athlete_id, checkpoint_number, elapsed_seconds)
        st.session_state.message = f"Added missed split for {event.athlete_name} at {event.checkpoint_label}."
        st.session_state.recovery_mode = ""
        return True
    except Exception as exc:
        _show_persistence_error("Add missed split", exc)
        st.error(str(exc))
        return False


def _reassign_event(event, athlete_id: str) -> bool:
    try:
        persist_athlete_reassignment(st.session_state, event, athlete_id)
        st.session_state.message = "Split reassigned. All shared views will refresh from the audit history."
        st.session_state.recovery_mode = ""
        return True
    except Exception as exc:
        _show_persistence_error("Reassign split", exc)
        st.error(f"This timing event could not be changed: {exc} Race data has been refreshed.")
        return False


def _event_details(event) -> None:
    st.markdown(f"**{event.athlete_name}**")
    st.write(event.checkpoint_label)
    st.write(event.recorded_at.strftime("%I:%M:%S %p UTC"))
    st.write(f"Elapsed: **{format_duration(event.elapsed_seconds)}**")
    st.caption(f"Event {event.id} • Athlete {event.athlete_id}")


def _render_timing_recovery(projection, clock) -> None:
    race_session_id = st.session_state.get("active_race_session_id")
    events = tuple(st.session_state.get("persisted_split_events", ()))
    st.subheader("Timing Controls")
    st.caption("Corrections are separate from normal athlete buttons and preserve the original event history.")
    undo, correct, missed = st.columns(3)
    recovery_locked = not race_session_id or clock.status == "ended"
    if undo.button("↶ Undo Last Split", use_container_width=True, disabled=recovery_locked):
        st.session_state.recovery_mode = "undo"
    if correct.button("Correct Split", use_container_width=True, disabled=recovery_locked):
        st.session_state.recovery_mode = "correct"
    if missed.button("Add Missed Split", use_container_width=True, disabled=not race_session_id or clock.status not in {"running", "paused"}):
        st.session_state.recovery_mode = "missed"

    mode = st.session_state.get("recovery_mode", "")
    if recovery_locked:
        mode = ""
        st.session_state.recovery_mode = ""
        if clock.status == "ended":
            st.caption("Reopen the race before using correction tools.")
    if mode == "undo":
        requested_id = st.session_state.get("recovery_event_id")
        event = next((item for item in active_events_for_athlete(events, race_session_id, next((candidate.athlete_id for candidate in events if candidate.id == requested_id), "")) if item.id == requested_id), None) if requested_id else latest_active_event(events, race_session_id)
        with st.container(border=True):
            st.markdown("### Undo last recorded split?")
            if event is None:
                st.info("There is no active split to undo in this race session.")
            else:
                _event_details(event)
                cancel, confirm = st.columns(2)
                if cancel.button("Cancel", key="cancel_last_split", use_container_width=True):
                    st.session_state.recovery_mode = ""
                    st.session_state.recovery_event_id = None
                    st.rerun()
                if confirm.button("Undo Split", key=f"undo_event:{event.id}", use_container_width=True):
                    if _correct_event(event, require_latest=not requested_id):
                        st.session_state.recovery_event_id = None
                        st.rerun()

    elif mode == "correct" and projection:
        with st.container(border=True):
            st.markdown("### Correct a Specific Split")
            athlete_options = [state.athlete for state in projection.athletes]
            requested_id = st.session_state.get("recovery_event_id")
            requested_event = next((item for item in events if item.id == requested_id), None)
            athlete_id = requested_event.athlete_id if requested_event else st.selectbox(
                "Athlete", [athlete.athlete_id for athlete in athlete_options],
                format_func=lambda value: next(athlete.name for athlete in athlete_options if athlete.athlete_id == value),
                key="correction_athlete_id",
            ) if athlete_options else None
            athlete_events = active_events_for_athlete(events, race_session_id, athlete_id) if athlete_id else []
            if not athlete_events:
                st.info("This athlete has no active recorded checkpoints.")
            else:
                event_id = requested_event.id if requested_event else st.selectbox(
                    "Recorded checkpoint", [event.id for event in athlete_events],
                    format_func=lambda value: next(f"{event.checkpoint_label} • {format_duration(event.elapsed_seconds)}" for event in athlete_events if event.id == value),
                    key="correction_event_id",
                )
                event = next(event for event in athlete_events if event.id == event_id)
                _event_details(event)
                if any(item.checkpoint_number > event.checkpoint_number for item in athlete_events):
                    st.warning("Later checkpoints remain in history but will be held out of progress until this missing checkpoint is replaced.")
                destinations = [athlete for athlete in athlete_options if athlete.athlete_id != event.athlete_id]
                destination_id = st.selectbox("Change athlete to", [athlete.athlete_id for athlete in destinations], format_func=lambda value: next(athlete.name for athlete in destinations if athlete.athlete_id == value), key=f"reassign:{event.id}") if destinations else None
                confirm = st.checkbox("I confirm this split belongs to the selected athlete.", key=f"confirm_correction:{event.id}")
                cancel, apply = st.columns(2)
                if cancel.button("Cancel", key="cancel_specific_correction", use_container_width=True):
                    st.session_state.recovery_mode = ""; st.session_state.recovery_event_id = None; st.rerun()
                if apply.button("Confirm Reassignment", key=f"correct_event:{event.id}", disabled=not confirm or not destination_id, use_container_width=True):
                    if _reassign_event(event, destination_id):
                        st.session_state.recovery_event_id = None
                        st.rerun()

    elif mode == "missed" and projection:
        with st.container(border=True):
            st.markdown("### Add a Missed Split")
            eligible = [state for state in projection.athletes if state.next_checkpoint is not None]
            athlete_id = st.selectbox(
                "Athlete", [state.athlete.athlete_id for state in eligible],
                format_func=lambda value: next(state.athlete.name for state in eligible if state.athlete.athlete_id == value),
                key="manual_split_athlete_id",
            ) if eligible else None
            athlete_state = next((state for state in eligible if state.athlete.athlete_id == athlete_id), None)
            if athlete_state:
                checkpoint = athlete_state.next_checkpoint
                st.write(f"Missing checkpoint: **{checkpoint.label}**")
                elapsed_text = st.text_input("Official elapsed race time", placeholder="MM:SS or H:MM:SS", key="manual_split_elapsed")
                elapsed = parse_time_to_seconds(elapsed_text)
                st.caption("Enter the elapsed race-clock time observed for this athlete. The correction action timestamp is recorded separately.")
                if elapsed_text and elapsed is None:
                    st.error("Enter a positive elapsed time as MM:SS or H:MM:SS.")
                confirm = st.checkbox("I confirm this athlete, checkpoint, and elapsed time.", key="confirm_manual_split")
                cancel, apply = st.columns(2)
                if cancel.button("Cancel", key="cancel_manual_split", use_container_width=True):
                    st.session_state.recovery_mode = ""; st.rerun()
                if apply.button("Add Missed Split", key=f"add_manual:{athlete_id}:{checkpoint.number}", disabled=not confirm or elapsed is None, use_container_width=True):
                    if _add_missed_split(athlete_id, checkpoint.number, elapsed): st.rerun()

    st.subheader("Recent Activity")
    activity = recent_timing_activity(events, race_session_id, limit=8) if race_session_id else []
    if not activity:
        st.caption("No timing activity in this race session yet.")
    active_ids = {active.id for athlete in projection.athletes for active in active_events_for_athlete(events, race_session_id, athlete.athlete.athlete_id)} if projection else set()
    event_by_id = {event.id: event for event in events}
    for item in activity:
        row, undo_action, correct_action = st.columns([5, 2, 2])
        row.write(f"**{item.occurred_at.strftime('%H:%M:%S')}** — {item.label}")
        event = event_by_id.get(item.event_id)
        enabled = event is not None and event.id in active_ids and not recovery_locked
        if undo_action.button("Undo", key=f"recent_undo:{item.event_id}", disabled=not enabled, use_container_width=True):
            st.session_state.recovery_event_id = item.event_id
            st.session_state.recovery_mode = "undo"
            st.rerun()
        if correct_action.button("Correct", key=f"recent_correct:{item.event_id}", disabled=not enabled, use_container_width=True):
            st.session_state.recovery_event_id = item.event_id
            st.session_state.recovery_mode = "correct"
            st.rerun()
    corrections = [item for item in activity if item.is_correction]
    with st.expander("Correction History"):
        if not corrections:
            st.caption("No corrections in this race session.")
        for item in corrections:
            st.write(f"**{item.occurred_at.strftime('%H:%M:%S')}** — {item.label}")


def _render_finish_controls(projection, clock) -> None:
    race_session_id = st.session_state.get("active_race_session_id")
    if not race_session_id or projection is None:
        return
    finished = [state for state in projection.athletes if state.finished]
    dnf = [state for state in projection.athletes if state.outcome_status == "dnf"]
    unresolved = [state for state in projection.athletes if not state.finished and state.outcome_status != "dnf"]
    st.subheader("Race Controls")
    if clock.status == "ended":
        awaiting_review = st.session_state.get("persisted_race_status") == "awaiting_review"
        st.success("## TIMING COMPLETE — AWAITING REVIEW" if awaiting_review else "## RACE FINISHED\nTiming and corrections are locked.")
        if st.button("Review Results", type="primary", use_container_width=True):
            st.session_state.selected_results_session_id = race_session_id
            if awaiting_review:
                st.session_state.results_review_session_id = race_session_id
            st.switch_page(st.session_state.page_registry["results"])
        if awaiting_review:
            st.caption("Live capture is stopped. Existing splits and audit history are preserved for coach review.")
            return
        if st.button("Reopen Race", use_container_width=True):
            st.session_state.reopen_confirmation = True
        if st.session_state.get("reopen_confirmation"):
            with st.container(border=True):
                st.markdown(f"### Reopen {st.session_state.meet_config.race_name}?")
                st.write("This will allow timing and corrections again. Existing splits, corrections, and DNF records will not be deleted.")
                cancel, confirm = st.columns(2)
                if cancel.button("Cancel", key="cancel_reopen", use_container_width=True):
                    st.session_state.reopen_confirmation = False; st.rerun()
                if confirm.button("Reopen Race", key="confirm_reopen", use_container_width=True):
                    try:
                        persist_reopen(st.session_state)
                        st.session_state.reopen_confirmation = False
                        st.session_state.message = "Race reopened in a paused state. Resume when ready."
                        st.rerun()
                    except Exception as exc:
                        _show_persistence_error("Reopen race", exc); st.error(str(exc))
        return

    if st.button("End Race Timing", type="primary", use_container_width=True, disabled=clock.status not in {"running", "paused"}):
        st.session_state.end_timing_confirmation = True
    if not st.session_state.get("end_timing_confirmation"):
        return
    with st.container(border=True):
        st.markdown("### End race timing?")
        st.write("Live capture will stop. Existing timing data will be preserved. Results can be verified and corrected later.")
        st.write(f"**Athletes:** {len(projection.athletes)}  \n**Finished:** {len(finished)}  \n**DNF:** {len(dnf)}  \n**Still unresolved:** {len(unresolved)}")
        st.caption(f"Race session: {race_session_id}")
        cancel, confirm = st.columns(2)
        if cancel.button("Keep Timing", key="cancel_end_timing", use_container_width=True):
            st.session_state.end_timing_confirmation = False; st.rerun()
        if confirm.button("End Race Timing", key="confirm_end_timing", type="primary", use_container_width=True):
            try:
                persist_timing_complete(st.session_state)
                st.session_state.end_timing_confirmation = False
                st.session_state.selected_results_session_id = race_session_id
                st.session_state.results_review_session_id = race_session_id
                st.switch_page(st.session_state.page_registry["results"])
            except Exception as exc:
                _show_persistence_error("End race timing", exc); st.error(str(exc))


def _render_finish_timer_end_control(clock, checkpoint) -> None:
    """Render the timer lifecycle action only for an assigned finish snapshot."""
    if checkpoint is None or not checkpoint.is_finish or clock.status not in {"running", "paused"}:
        return
    st.markdown("### Finish Line Controls")
    if st.button("End Race Timing", key="finish_timer_end_timing", type="primary", use_container_width=True):
        st.session_state.finish_timer_end_confirmation = True
    if not st.session_state.get("finish_timer_end_confirmation"):
        return
    with st.container(border=True):
        st.markdown("### End race timing?")
        st.write("Live capture will stop. Existing timing data will be preserved. Results can be verified and corrected later.")
        cancel, confirm = st.columns(2)
        if cancel.button("Keep Timing", key="cancel_finish_timer_end", use_container_width=True):
            st.session_state.finish_timer_end_confirmation = False
            st.rerun()
        if confirm.button("End Race Timing", key="confirm_finish_timer_end", type="primary", use_container_width=True):
            try:
                persist_timing_complete(
                    st.session_state,
                    finish_checkpoint_number=checkpoint.number,
                )
                st.session_state.finish_timer_end_confirmation = False
                st.session_state.message = "Race timing ended. Results are awaiting coach review."
                st.rerun()
            except Exception as exc:
                _show_persistence_error("End race timing", exc)
                st.error(str(exc))


def render() -> None:
    """Render the existing controlled live-timing polling fragment."""
    st.markdown(_BUTTON_CSS, unsafe_allow_html=True)
    identity = st.session_state.get("app_identity")
    coach_timing_mode = is_race_day_timing_mode(st.session_state, identity)
    timer_mode = bool(st.session_state.get("timer_mode") and is_timing_operator(st.session_state, identity))
    station_number = st.session_state.get("timer_station_checkpoint") if timer_mode else None
    if is_timing_operator(st.session_state, identity) and station_number is None:
        st.warning("Select a race and checkpoint before opening the timing screen.")
        if st.button("Select Timing Station", type="primary", use_container_width=True):
            st.switch_page(st.session_state.page_registry["race_day_timer"])
        return
    st.session_state.last_fragment_rerun_at = datetime.now(timezone.utc)
    _restore_if_needed()
    # Poll the exact connected row even while the local clock is not_started.
    # This is what lets a waiting browser observe another coach's start.
    skip_poll = st.session_state.pop("skip_next_live_poll", False)
    if st.session_state.get("active_race_session_id") and not skip_poll:
        poll_shared_timing(st.session_state)
    if timer_mode:
        _heartbeat_timer_station()
    config = st.session_state.meet_config
    clock = st.session_state.race_clock
    valid_setup = setup_is_valid(st.session_state)
    status = STATUS_LABELS[clock.status]
    if st.session_state.get("persisted_race_status") == "awaiting_review":
        status = "Awaiting Review"

    render_school_header(
        st.session_state.school_profile,
        config.race_name or "Live Timing",
        subtitle=f"{config.meet_name or 'Meet not selected'} • {status}",
        compact=True,
    )
    checkpoint = None
    if timer_mode:
        checkpoint = next(
            (item for item in config.checkpoints if item.number == station_number), None
        )
        station_name = station_label(checkpoint) if checkpoint else "Unknown checkpoint"
        st.success(f"**TIMING STATION: {station_name}**")
        control_columns = st.columns(2) if coach_timing_mode else [st]
        if control_columns[0].button("Change Station", use_container_width=True):
            change_timing_station(st.session_state)
            st.switch_page(st.session_state.page_registry["race_day_timer"])
        if coach_timing_mode and control_columns[1].button("Exit Timing Mode", use_container_width=True):
            exit_race_day_timing_mode(st.session_state)
            st.switch_page(st.session_state.page_registry["meet_dashboard"])
    repository_result = st.session_state.get("repository_result")
    if repository_result is not None and repository_result.is_temporary:
        st.error(
            "Shared live timing requires Supabase. Starting or recording a shared race is disabled; the app will not fall back to an isolated browser stopwatch."
        )
    connected_id = st.session_state.get("active_race_session_id") or "Not connected"
    sync_at = st.session_state.get("last_sync_at")
    storage = (
        "Connected"
        if st.session_state.get("storage_connected")
        else (
            "Unavailable" if st.session_state.get("sync_error") else "Not synchronized"
        )
    )
    sync_label, sync_class = _sync_status()
    top_status = st.container()
    with top_status:
        st.markdown(f'<p class="{sync_class}">{sync_label}</p>', unsafe_allow_html=True)
        st.caption(
            f"{status} • {sync_at.strftime('%H:%M:%S UTC') if sync_at else 'Connecting'}"
        )
    if st.session_state.get("sync_error"):
        st.warning(
            "Connection problem. Existing race data remains visible and retry is automatic."
        )
    if clock.status == "ended":
        st.success("**TIMING COMPLETE — AWAITING REVIEW.**" if st.session_state.get("persisted_race_status") == "awaiting_review" else "**RACE FINISHED — Timing is locked.**")
    if st.session_state.get("debug_mode"):
        with st.expander("Development synchronization status", expanded=False):
            poll_at = st.session_state.get("poll_cycle_at")
            latest_at = st.session_state.get("latest_event_at")
            action = st.session_state.get("last_split_action") or {}
            st.code(
                "\n".join(
                    [
                        f"timer_name: {st.session_state.timer_name or 'not set'}",
                        f"race_session_id: {connected_id}",
                        f"initiated_start: {st.session_state.get('initiated_start_session_id') == connected_id}",
                        f"last_fragment_rerun: {st.session_state.last_fragment_rerun_at.isoformat()}",
                        f"poll_cycle: {st.session_state.get('poll_cycle_count', 0)}",
                        f"poll_cycle_at: {poll_at.isoformat() if poll_at else 'never'}",
                        f"last_successful_sync: {sync_at.isoformat() if sync_at else 'never'}",
                        f"loaded_active_events: {st.session_state.get('loaded_split_event_count', 0)}",
                        f"latest_event_id: {st.session_state.get('latest_event_id') or 'none'}",
                        f"latest_event_at: {latest_at.isoformat() if latest_at else 'none'}",
                        f"local_clock_status: {clock.status}",
                        f"persisted_session_status: {st.session_state.get('persisted_race_status') or 'unknown'}",
                        f"persisted_started_at: {st.session_state.get('persisted_started_at') or 'none'}",
                        f"projected_event_count: {len(getattr(st.session_state.get('projected_race_state'), 'events', ())) }",
                        f"projected_results_row_count: {len(getattr(st.session_state.get('projected_race_state'), 'results_rows', ())) }",
                        f"sync_error: {st.session_state.get('sync_error') or 'none'}",
                        f"last_write_attempt: {action.get('click_received_at') if action else 'none'}",
                        f"last_write_success: {action.get('result') == 'inserted' if action else False}",
                        f"last_write_event_id: {action.get('inserted_event_id') or 'none' if action else 'none'}",
                        f"last_write_error: {action.get('error') or 'none' if action else 'none'}",
                    ]
                ),
                language="text",
            )
            if action:
                st.code(
                    "\n".join(
                        [
                            "last_split_action:",
                            f"  timer_name: {action.get('timer_name') or 'not set'}",
                            f"  athlete: {action.get('athlete_name') or 'unknown'} ({action.get('athlete_id') or 'unknown'})",
                            f"  race_session_id: {action.get('race_session_id') or 'none'}",
                            f"  intended_checkpoint: {action.get('checkpoint_number')} / {action.get('checkpoint_label') or 'unknown'}",
                            f"  elapsed_seconds: {action.get('elapsed_seconds')}",
                            f"  click_received_at: {action.get('click_received_at')}",
                            f"  result: {action.get('result')}",
                            f"  inserted_event_id: {action.get('inserted_event_id') or 'none'}",
                            f"  events_after_reload: {action.get('events_after_reload')}",
                            f"  error: {action.get('error') or 'none'}",
                            "  timings_ms:",
                            *[
                                f"    {name}: {duration:.2f}"
                                for name, duration in action.get(
                                    "timings_ms", {}
                                ).items()
                            ],
                        ]
                    ),
                    language="text",
                )
    if st.session_state.get("active_race_session_id") and clock.status == "not_started":
        st.info(
            f"Waiting for race to start • Session **{connected_id}** • "
            f"Timer **{st.session_state.timer_name or 'Name required'}** • Storage **{storage}**"
        )
    st.caption(
        f"**{config.meet_name or 'Meet required'} • {config.race_name or 'Race required'}** · "
        f"{format_distance(config.race_distance_meters)} · {len(config.checkpoints)} checkpoints"
    )

    if not valid_setup:
        st.warning(
            "Complete Race Setup before starting the race. Meet name, race name, checkpoints, and at least one athlete are required."
        )

    shared_unavailable = (
        repository_result is not None and repository_result.is_temporary
    )
    finish_line_starter = bool(
        timer_mode
        and checkpoint is not None
        and checkpoint.is_finish
    )
    if finish_line_starter and clock.status == "not_started":
        st.info("You are the race starter. Confirm the course is ready, then start the shared race clock.")
        if st.button(
            "Start Race",
            type="primary",
            use_container_width=True,
            disabled=shared_unavailable or not valid_setup,
        ):
            if _start_timing():
                st.rerun()
    if timer_mode:
        _render_finish_timer_end_control(clock, checkpoint)
    if not timer_mode:
        quick_start, quick_pause, quick_resume = st.columns(3)
        if quick_start.button(
            "Start Race",
            use_container_width=True,
            disabled=shared_unavailable
            or not valid_setup
            or clock.status == "running"
            or clock.status == "ended",
        ):
            if _start_timing():
                st.rerun()
        if quick_pause.button(
            "Pause", use_container_width=True, disabled=clock.status != "running"
        ):
            if _pause_timing():
                st.rerun()
        if quick_resume.button(
            "Resume", use_container_width=True, disabled=clock.status != "paused"
        ):
            if _resume_timing():
                st.rerun()

        with st.expander("Race Controls", expanded=False):
            timer_name = st.text_input(
                "Timer / display name",
                value=st.session_state.timer_name,
                placeholder="e.g. Finish line tablet",
            )
            st.session_state.timer_name = timer_name.strip()
            st.caption(f"Session: {connected_id} • Storage: {storage}")
            c3 = st.container()
            confirm_reset = c3.checkbox("Confirm reset")
            if c3.button(
                "Reset Race", use_container_width=True, disabled=not confirm_reset
            ):
                _reset_timing()

    if st.session_state.message:
        st.info(st.session_state.message)
    if not st.session_state.timer_name:
        st.warning(
            "Set a Timer / display name in Race Controls before recording splits."
        )

    st.subheader("Record Athlete Split")
    # Render the existing authoritative clock in the position coaches watch;
    # this adds no state, queries, or polling.
    _clock_metric()
    if not st.session_state.athletes:
        st.warning("Add athletes on the Race Setup page before timing a race.")
        return
    if (
        not st.session_state.get("active_race_session_id")
        or not st.session_state.meet_config.checkpoints
    ):
        st.warning(
            "Athlete buttons are disabled until an authoritative race session and checkpoint snapshot are loaded."
        )

    projection = st.session_state.get("projected_race_state")
    if timer_mode:
        st.markdown("### Timing Mode")
        timing_mode = st.session_state.get("timer_timing_mode", "pack")
        if timing_mode == "pack":
            st.success("⚡ Pack Mode")
            if st.button("Switch to Individual Timing", key="timer_individual_mode", use_container_width=True):
                st.session_state.timer_timing_mode = "individual"
                st.session_state.pack_mode_active = False
                st.rerun()
        elif st.button("Switch to Pack Mode", key="timer_pack_mode", type="primary", use_container_width=True):
            st.session_state.timer_timing_mode = "pack"
            st.session_state.pack_mode_active = True
            st.rerun()
    pack_active = _render_pack_mode(
        projection,
        clock,
        shared_unavailable,
        station_number if timer_mode else None,
    ) if not timer_mode or st.session_state.get("timer_timing_mode", "pack") == "pack" else False
    if timer_mode and st.session_state.get("timer_timing_mode", "pack") == "pack":
        st.caption("Captures are saved on this device immediately and synchronize automatically.")
        return
    if pack_active:
        st.caption("Normal timing controls are temporarily hidden to prevent accidental duplicate taps. Exit Pack Mode to restore them.")
    search_col, order_col = st.columns([2, 1])
    search_value = search_col.text_input(
        "Find athlete",
        placeholder="Search name or bib",
        key="live_athlete_search",
    )
    order_mode = order_col.selectbox(
        "Button order",
        ["Stable", "Expected Arrival", "Race Order"],
        key="live_button_order",
        help="Stable preserves race-roster positions. Expected Arrival groups athletes by their next checkpoint.",
    )
    all_projected = (
        list(ordered_timing_athletes(projection, order_mode)) if projection else []
    )
    matching = [
        item for item in all_projected if athlete_matches_search(item, search_value)
    ]
    if timer_mode:
        matching = [
            item
            for item in matching
            if item.next_checkpoint is not None
            and item.next_checkpoint.number == station_number
        ]
    active_athletes, finished_athletes = partition_finished_athletes(matching)
    st.caption(f"{len(active_athletes)} active • {len(finished_athletes)} finished / DNF")

    def render_button_grid(athletes) -> None:
        columns_per_row = 2 if len(athletes) <= 10 else 3
        for index, athlete_state in enumerate(athletes):
            athlete = athlete_state.athlete
            if index % columns_per_row == 0:
                cols = st.columns(columns_per_row)
            next_cp = athlete_state.next_checkpoint
            disabled = athlete_timing_button_disabled(
                shared_unavailable=shared_unavailable,
                race_session_id=st.session_state.get("active_race_session_id"),
                clock_status=clock.status,
                timer_name=st.session_state.timer_name,
                checkpoint_number=next_cp.number if next_cp else None,
                finished=athlete_state.finished,
                # DNF is terminal for ordinary timing until explicitly reversed.
                reopened=athlete.reopened_after_finish,
            )
            if athlete_state.outcome_status == "dnf":
                disabled = True
            button_key = athlete_timing_button_key(
                st.session_state.get("active_race_session_id") or "unconnected",
                athlete.athlete_id,
                next_cp.number if next_cp else None,
            )
            with cols[index % columns_per_row]:
                st.button(
                    athlete_state.button_label,
                    key=button_key,
                    use_container_width=True,
                    disabled=disabled,
                    on_click=_record_tap,
                    args=(athlete.athlete_id,),
                    type="primary",
                )

    if not pack_active:
        render_button_grid(active_athletes)
    if not matching:
        st.info("No race athletes match that name or bib.")
    if finished_athletes:
        with st.expander(f"Finished / DNF ({len(finished_athletes)})", expanded=False):
            for item in finished_athletes:
                latest = item.splits[-1] if item.splits else None
                st.caption(
                    f"**{item.athlete.name}** • #{item.athlete.bib_number or '—'} • {'DNF' if item.outcome_status == 'dnf' else format_duration(latest.cumulative_time_seconds) if latest else 'Finished'}"
                )

    if not timer_mode:
        _render_timing_recovery(projection, clock)
        _render_finish_controls(projection, clock)

    if not timer_mode and all_projected and all(item.finished for item in all_projected):
        st.success("Race complete: all athletes have reached the finish.")
        if st.button("Go to Results", use_container_width=True):
            st.switch_page(st.session_state.page_registry["results"])

    if timer_mode:
        st.caption("Runners appear when this is their next checkpoint. Recorded runners are removed automatically.")
        return

    st.subheader("Live Split Board")
    filter_value = st.selectbox(
        "Board filter",
        ["All athletes", "Active", "Finished"],
        label_visibility="collapsed",
    )
    # Both controls and results consume the exact same projection snapshot.
    board = _live_board_frame(filter_value, search_value)
    if board.empty:
        st.caption("No athletes match this filter.")
    else:
        st.dataframe(board, hide_index=True, use_container_width=True)

    if st.session_state.get("debug_mode") and all_projected:
        with st.expander("Per-athlete synchronization diagnostics"):
            for item in all_projected:
                st.code(
                    "\n".join(
                        [
                            f"race_athlete_id: {item.athlete.athlete_id}",
                            f"athlete_name: {item.athlete.name}",
                            f"persisted_split_count: {item.completed_split_count}",
                            f"next_checkpoint_id: {item.next_checkpoint.number if item.next_checkpoint else 'none'}",
                            f"next_checkpoint_label: {item.next_checkpoint.label if item.next_checkpoint else 'none'}",
                            f"button_disabled: {not item.button_enabled}",
                            f"latest_split_event_id: {item.latest_split_event.id if item.latest_split_event else 'none'}",
                        ]
                    )
                )


# Preserve the original working fragment boundary: the page renderer itself is
# the single fragment. Do not wrap it in a second page/fragment architecture.
if hasattr(st, "fragment"):
    render = st.fragment(run_every=2)(render)
