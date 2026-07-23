"""Streamlit session-state helpers for the prototype."""

from __future__ import annotations

import time
from uuid import uuid4

from split_tracker.calculations import build_split_record, recalculate_athlete_splits
from split_tracker.models import Athlete, MeetConfig, RaceClock, SplitRecord

DUPLICATE_LOCKOUT_SECONDS = 1.5


def initialize_state(session_state) -> None:
    """Initialize required Streamlit session-state keys."""
    session_state.setdefault("meet_config", MeetConfig())
    session_state.setdefault("athletes", [])
    session_state.setdefault("splits", [])
    session_state.setdefault("race_clock", RaceClock())
    session_state.setdefault("last_tap", {})
    session_state.setdefault("split_sequence", 0)
    session_state.setdefault("message", "")


def elapsed_seconds(clock: RaceClock, now: float | None = None) -> float:
    """Return elapsed race time from a RaceClock."""
    current = time.perf_counter() if now is None else now
    if clock.status == "not_started":
        return 0.0
    if clock.status == "ended":
        return clock.ended_elapsed_seconds or 0.0
    if clock.start_perf_counter is None:
        return 0.0
    if clock.status == "paused":
        pause_at = clock.pause_started_at or current
        return max(0.0, pause_at - clock.start_perf_counter - clock.paused_total_seconds)
    return max(0.0, current - clock.start_perf_counter - clock.paused_total_seconds)


def start_race(session_state, now: float | None = None) -> None:
    current = time.perf_counter() if now is None else now
    session_state.race_clock = RaceClock(status="running", start_perf_counter=current)
    session_state.splits = []
    session_state.last_tap = {}
    session_state.split_sequence = 0
    session_state.message = "Race started."


def pause_race(session_state, now: float | None = None) -> None:
    clock = session_state.race_clock
    if clock.status != "running":
        return
    clock.pause_started_at = time.perf_counter() if now is None else now
    clock.status = "paused"
    session_state.race_clock = clock
    session_state.message = "Race paused."


def resume_race(session_state, now: float | None = None) -> None:
    clock = session_state.race_clock
    if clock.status != "paused":
        return
    current = time.perf_counter() if now is None else now
    if clock.pause_started_at is not None:
        clock.paused_total_seconds += current - clock.pause_started_at
    clock.pause_started_at = None
    clock.status = "running"
    session_state.race_clock = clock
    session_state.message = "Race resumed."


def end_race(session_state, now: float | None = None) -> None:
    clock = session_state.race_clock
    if clock.status not in {"running", "paused"}:
        return
    clock.ended_elapsed_seconds = elapsed_seconds(clock, now)
    clock.status = "ended"
    clock.pause_started_at = None
    session_state.race_clock = clock
    session_state.message = "Race ended."


def reset_race(session_state) -> None:
    session_state.race_clock = RaceClock()
    session_state.splits = []
    session_state.last_tap = {}
    session_state.split_sequence = 0
    session_state.message = "Race reset."


def record_split(session_state, athlete_id: str, now: float | None = None) -> SplitRecord | None:
    """Record a split for an athlete unless duplicate protection blocks it."""
    clock = session_state.race_clock
    if clock.status != "running":
        session_state.message = "Start or resume the race before recording splits."
        return None

    current = time.perf_counter() if now is None else now
    last_tap_time = session_state.last_tap.get(athlete_id)
    if last_tap_time is not None and current - last_tap_time < DUPLICATE_LOCKOUT_SECONDS:
        session_state.message = "Duplicate tap ignored."
        return None

    athlete = next((candidate for candidate in session_state.athletes if candidate.athlete_id == athlete_id), None)
    if athlete is None:
        session_state.message = "Athlete not found."
        return None

    session_state.split_sequence += 1
    athlete_splits = [split for split in session_state.splits if split.athlete_id == athlete_id]
    split = build_split_record(
        split_id=str(uuid4()),
        athlete=athlete,
        existing_athlete_splits=athlete_splits,
        elapsed_seconds=elapsed_seconds(clock, current),
        checkpoint_distance_miles=session_state.meet_config.checkpoint_distance_miles,
        race_distance_miles=session_state.meet_config.race_distance_miles,
        sequence=session_state.split_sequence,
    )
    session_state.splits.append(split)
    session_state.last_tap[athlete_id] = current
    session_state.message = f"Recorded split for {athlete.name}."
    return split


def undo_last_split(session_state) -> SplitRecord | None:
    if not session_state.splits:
        session_state.message = "No split to undo."
        return None
    last_split = max(session_state.splits, key=lambda split: split.sequence)
    session_state.splits = [split for split in session_state.splits if split.split_id != last_split.split_id]
    session_state.message = f"Undid split for {last_split.athlete_name}."
    return last_split


def replace_athlete_roster(session_state, athletes: list[Athlete]) -> None:
    session_state.athletes = athletes
    refresh_all_splits(session_state)


def refresh_all_splits(session_state) -> None:
    """Recalculate derived fields for all athletes using current setup."""
    updated: list[SplitRecord] = []
    for athlete in session_state.athletes:
        athlete_splits = [split for split in session_state.splits if split.athlete_id == athlete.athlete_id]
        updated.extend(
            recalculate_athlete_splits(
                athlete_splits,
                athlete,
                session_state.meet_config.checkpoint_distance_miles,
                session_state.meet_config.race_distance_miles,
            )
        )
    session_state.splits = sorted(updated, key=lambda split: split.sequence)
