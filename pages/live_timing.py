"""Live timing page."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from split_tracker.formatting import format_distance, format_duration
from split_tracker.timing_persistence import (
    persist_cancel,
    persist_completion,
    persist_pause,
    persist_resume,
    persist_undo_split,
    poll_shared_timing,
    record_authoritative_split,
    restore_timing_state,
    start_and_synchronize_shared_timing,
)
from split_tracker.state import (
    elapsed_seconds,
    end_race,
    pause_race,
    reopen_athlete,
    reset_race,
    resume_race,
    setup_is_valid,
    start_race,
    undo_last_split,
)

logger = logging.getLogger(__name__)

_BUTTON_CSS = """
<style>
div[data-testid="stButton"] > button {
    min-height: 5rem;
    font-size: 1.05rem;
    font-weight: 700;
    border-radius: 0.9rem;
    white-space: pre-wrap;
}
[data-testid="stMetricValue"] { font-size: 2.7rem; }
.finished-athlete { opacity: 0.65; }
</style>
"""

STATUS_LABELS = {
    "not_started": "Ready",
    "running": "Running",
    "paused": "Paused",
    "ended": "Finished",
}


def _clock_metric() -> None:
    st.metric("Race Clock", format_duration(elapsed_seconds(st.session_state.race_clock)))


def athlete_timing_button_key(race_session_id: str, athlete_id: str, checkpoint_number: int | None) -> str:
    """Return a stable identity for one session/athlete/checkpoint button."""
    checkpoint_key = "complete" if checkpoint_number is None else str(checkpoint_number)
    return f"split:{race_session_id}:{athlete_id}:{checkpoint_key}"


def athlete_timing_button_disabled(
    *, shared_unavailable: bool, race_session_id: str | None, clock_status: str,
    timer_name: str, checkpoint_number: int | None, finished: bool, reopened: bool,
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


def _live_board_frame(filter_value: str) -> pd.DataFrame:
    rows = []
    projection = st.session_state.get("projected_race_state")
    for athlete_state in projection.athletes if projection else ():
        athlete = athlete_state.athlete
        latest = athlete_state.splits[-1] if athlete_state.splits else None
        finished = athlete_state.finished
        if filter_value == "Active" and finished:
            continue
        if filter_value == "Finished" and not finished:
            continue
        rows.append(
            {
                "Athlete": athlete.name,
                "Bib": athlete.bib_number,
                "Latest checkpoint": latest.checkpoint_label if latest else "—",
                "Checkpoint order": latest.checkpoint_number if latest else 0,
                "Latest segment": format_duration(latest.segment_split_seconds) if latest else "—",
                "Cumulative time": format_duration(latest.cumulative_time_seconds) if latest else "—",
                "Target variance": format_duration(latest.target_variance_seconds) if latest and latest.target_variance_seconds is not None else "—",
                "Finish status": "Finished" if finished else "Active",
                "Sort time": latest.cumulative_time_seconds if latest else float("inf"),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.sort_values(["Checkpoint order", "Sort time"], ascending=[False, True])
    return frame.drop(columns=["Checkpoint order", "Sort time"])



def _has_persisted_race() -> bool:
    result = st.session_state.get("repository_result")
    shared_storage = result is None or not result.is_temporary
    return bool(shared_storage and st.session_state.get("selected_race_id") and st.session_state.get("repository"))


def _show_persistence_error(operation: str, exc: Exception) -> None:
    logger.exception("Live timing persistence failed", extra={"operation": operation, "race_id": st.session_state.get("selected_race_id")})
    st.error(f"{operation} could not be saved. The underlying error was logged; no Supabase secrets were displayed.")


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
        current_elapsed = elapsed_seconds(st.session_state.race_clock)
        if _has_persisted_race():
            persist_pause(st.session_state, current_elapsed)
        pause_race(st.session_state)
        return True
    except Exception as exc:
        _show_persistence_error("Pause race", exc)
        return False


def _resume_timing() -> bool:
    try:
        if _has_persisted_race():
            persist_resume(st.session_state)
        resume_race(st.session_state)
        return True
    except Exception as exc:
        _show_persistence_error("Resume race", exc)
        return False


def _end_timing() -> bool:
    try:
        current_elapsed = elapsed_seconds(st.session_state.race_clock)
        if _has_persisted_race():
            persist_completion(st.session_state, current_elapsed)
        end_race(st.session_state)
        return True
    except Exception as exc:
        _show_persistence_error("End race", exc)
        return False


def _reset_timing() -> bool:
    try:
        current_elapsed = elapsed_seconds(st.session_state.race_clock)
        if _has_persisted_race() and st.session_state.get("active_race_session_id"):
            persist_cancel(st.session_state, current_elapsed)
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
            st.warning(f"{result.message} Shared progress was reloaded; use the newly displayed next checkpoint.")
        return True
    except Exception as exc:
        _show_persistence_error("Record split", exc)
        st.session_state.message = f"Split was not saved: {exc} Tap again after resolving the error."
        return False


def _undo_tap(split) -> bool:
    try:
        if _has_persisted_race() and st.session_state.get("active_race_session_id"):
            persist_undo_split(st.session_state, split)
            st.session_state.message = f"Undid {split.athlete_name} at {split.checkpoint_label}."
        else:
            undo_last_split(st.session_state)
        return True
    except Exception as exc:
        _show_persistence_error("Undo split", exc)
        return False

def render() -> None:
    """Render the existing controlled live-timing polling fragment."""
    st.markdown(_BUTTON_CSS, unsafe_allow_html=True)
    st.session_state.last_fragment_rerun_at = datetime.now(timezone.utc)
    _restore_if_needed()
    # Poll the exact connected row even while the local clock is not_started.
    # This is what lets a waiting browser observe another coach's start.
    if st.session_state.get("active_race_session_id"):
        poll_shared_timing(st.session_state)
    config = st.session_state.meet_config
    clock = st.session_state.race_clock
    valid_setup = setup_is_valid(st.session_state)
    status = STATUS_LABELS[clock.status]

    st.title("Live Timing")
    repository_result = st.session_state.get("repository_result")
    if repository_result is not None and repository_result.is_temporary:
        st.error("Shared live timing requires Supabase. Starting or recording a shared race is disabled; the app will not fall back to an isolated browser stopwatch.")
    timer_name = st.text_input("Timer / display name", value=st.session_state.timer_name, placeholder="e.g. Finish line tablet")
    st.session_state.timer_name = timer_name.strip()
    connected_id = st.session_state.get("active_race_session_id") or "Not connected"
    sync_at = st.session_state.get("last_sync_at")
    storage = "Connected" if st.session_state.get("storage_connected") else ("Unavailable" if st.session_state.get("sync_error") else "Not synchronized")
    st.caption(
        f"Session: **{connected_id}** • Timer: **{st.session_state.timer_name or 'Name required'}** • "
        f"Storage: **{storage}** • Last sync: **{sync_at.strftime('%H:%M:%S UTC') if sync_at else 'Never'}**"
    )
    if st.session_state.get("latest_shared_action"):
        st.caption(f"Latest action: **{st.session_state.latest_shared_action}**")
    if st.session_state.get("sync_error"):
        st.error(f"Shared timing synchronization failed: {st.session_state.sync_error}. Existing shared data remains displayed; retry is automatic.")
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
                    ]
                ),
                language="text",
            )
    if st.session_state.get("active_race_session_id") and clock.status == "not_started":
        st.info(
            f"Waiting for race to start • Session **{connected_id}** • "
            f"Timer **{st.session_state.timer_name or 'Name required'}** • Storage **{storage}**"
        )
    h1, h2, h3 = st.columns([2, 1, 1])
    h1.subheader(f"{config.meet_name or 'Meet required'} • {config.race_name or 'Race required'}")
    h2.metric("Distance", format_distance(config.race_distance_meters))
    h3.metric("Splits", len(st.session_state.splits))
    st.caption(f"Status: **{status}** • Checkpoints: {len(config.checkpoints)}")
    _clock_metric()

    if not valid_setup:
        st.warning("Complete Meet Setup before starting the race. Meet name, race name, checkpoints, and at least one athlete are required.")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    shared_unavailable = repository_result is not None and repository_result.is_temporary
    if c1.button("Start", use_container_width=True, disabled=shared_unavailable or not valid_setup or clock.status == "running" or (clock.status == "ended" and bool(st.session_state.splits))):
        if _start_timing():
            st.rerun()
    if c2.button("Pause", use_container_width=True, disabled=clock.status != "running"):
        if _pause_timing():
            st.rerun()
    if c3.button("Resume", use_container_width=True, disabled=clock.status != "paused"):
        if _resume_timing():
            st.rerun()

    confirm_end = c4.checkbox("Confirm end")
    if c4.button("End Race", use_container_width=True, disabled=clock.status not in {"running", "paused"} or not confirm_end):
        if _end_timing():
            st.rerun()

    last_split = max(st.session_state.splits, key=lambda split: split.sequence) if st.session_state.splits else None
    if last_split:
        c5.caption(f"Undo: {last_split.athlete_name} {last_split.checkpoint_label}")
    confirm_undo = c5.checkbox("Confirm undo")
    if c5.button("Undo Last Tap", use_container_width=True, disabled=not last_split or not confirm_undo):
        if _undo_tap(last_split):
            st.rerun()

    confirm_reset = c6.checkbox("Confirm reset")
    if c6.button("Reset Race", use_container_width=True, disabled=not confirm_reset):
        _reset_timing()

    if st.session_state.message:
        st.info(st.session_state.message)

    st.subheader("Athlete Timing Buttons")
    if not st.session_state.athletes:
        st.warning("Add athletes on the Meet Setup page before timing a race.")
        return
    if not st.session_state.get("active_race_session_id") or not st.session_state.meet_config.checkpoints:
        st.warning("Athlete buttons are disabled until an authoritative race session and checkpoint snapshot are loaded.")

    columns_per_row = 2 if len(st.session_state.athletes) <= 10 else 3
    projection = st.session_state.get("projected_race_state")
    projected_athletes = list(projection.athletes) if projection else []
    for index, athlete_state in enumerate(projected_athletes):
        athlete = athlete_state.athlete
        if index % columns_per_row == 0:
            cols = st.columns(columns_per_row)
        finished = athlete_state.finished
        next_cp = athlete_state.next_checkpoint
        disabled = athlete_timing_button_disabled(
            shared_unavailable=shared_unavailable,
            race_session_id=st.session_state.get("active_race_session_id"),
            clock_status=clock.status,
            timer_name=st.session_state.timer_name,
            checkpoint_number=next_cp.number if next_cp else None,
            finished=finished,
            reopened=athlete.reopened_after_finish,
        )
        button_key = athlete_timing_button_key(
            st.session_state.get("active_race_session_id") or "unconnected",
            athlete.athlete_id,
            next_cp.number if next_cp else None,
        )
        with cols[index % columns_per_row]:
            if st.button(athlete_state.button_label, key=button_key, use_container_width=True, disabled=disabled):
                if _record_tap(athlete.athlete_id):
                    st.rerun()
            if finished and st.button("Reopen athlete", key=f"reopen_{athlete.athlete_id}", use_container_width=True):
                reopen_athlete(st.session_state, athlete.athlete_id)

    if projected_athletes and all(item.finished for item in projected_athletes):
        st.success("Race complete: all athletes have reached the finish.")
        if st.button("Go to Results", use_container_width=True):
            st.switch_page(st.session_state.page_registry["results"])

    st.subheader("Live Split Board")
    filter_value = st.selectbox("Filter", ["All athletes", "Active", "Finished"], label_visibility="collapsed")
    # Both controls and results consume the exact same projection snapshot.
    board = _live_board_frame(filter_value)
    if board.empty:
        st.caption("No athletes match this filter.")
    else:
        st.dataframe(board, hide_index=True, use_container_width=True)

    if st.session_state.get("debug_mode") and projected_athletes:
        with st.expander("Per-athlete synchronization diagnostics"):
            for item in projected_athletes:
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
