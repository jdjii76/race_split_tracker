"""Streamlit session-state helpers for the prototype."""

from __future__ import annotations

import time
from uuid import uuid4

from split_tracker.calculations import athlete_finished, build_split_record, recalculate_athlete_splits
from split_tracker.models import Athlete, Checkpoint, MeetConfig, RaceClock, SplitRecord

DUPLICATE_LOCKOUT_SECONDS = 2.0


def initialize_state(session_state) -> None:
    """Initialize required Streamlit session-state keys."""
    session_state.setdefault("meet_config", MeetConfig())
    session_state.setdefault("athletes", [])
    session_state.setdefault("splits", [])
    session_state.setdefault("race_clock", RaceClock())
    session_state.setdefault("last_tap", {})
    session_state.setdefault("split_sequence", 0)
    session_state.setdefault("message", "")
    session_state.setdefault("pending_duplicate", None)
    session_state.setdefault("setup_saved", False)


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


def validate_setup(config: MeetConfig, athletes: list[Athlete]) -> list[str]:
    """Return validation errors for meet setup."""
    errors: list[str] = []
    if not config.meet_name.strip():
        errors.append("Meet name is required.")
    if not config.race_name.strip():
        errors.append("Race name is required.")
    if config.race_distance_meters <= 0:
        errors.append("Race distance must be greater than zero.")
    if not config.checkpoints:
        errors.append("At least one checkpoint is required.")
    if not athletes:
        errors.append("At least one athlete is required.")
    bibs = [athlete.bib_number for athlete in athletes if athlete.bib_number]
    if len(bibs) != len(set(bibs)):
        errors.append("Bib numbers must be unique when entered.")
    for athlete in athletes:
        if not athlete.name.strip():
            errors.append("Athlete name is required.")
            break
    return errors


def setup_is_valid(session_state) -> bool:
    """Return whether the current setup can start a race."""
    return not validate_setup(session_state.meet_config, session_state.athletes)


def start_race(session_state, now: float | None = None) -> bool:
    """Start the race without silently overwriting finished results."""
    if not setup_is_valid(session_state):
        session_state.message = "Complete and save a valid setup before starting."
        return False
    if session_state.splits and session_state.race_clock.status == "ended":
        session_state.message = "Reset the race before starting again."
        return False
    current = time.perf_counter() if now is None else now
    session_state.race_clock = RaceClock(status="running", start_perf_counter=current)
    if not session_state.splits:
        session_state.last_tap = {}
        session_state.split_sequence = 0
    session_state.message = "Race started."
    return True


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
    session_state.pending_duplicate = None
    session_state.message = "Race reset."


def athlete_splits(session_state, athlete_id: str) -> list[SplitRecord]:
    """Return ordered splits for one athlete."""
    return sorted([split for split in session_state.splits if split.athlete_id == athlete_id], key=lambda split: split.sequence)


def is_athlete_finished(session_state, athlete_id: str) -> bool:
    """Return whether an athlete has completed all checkpoints."""
    athlete = next((candidate for candidate in session_state.athletes if candidate.athlete_id == athlete_id), None)
    if athlete and athlete.reopened_after_finish:
        return False
    return athlete_finished(athlete_splits(session_state, athlete_id), session_state.meet_config.checkpoints)


def reopen_athlete(session_state, athlete_id: str) -> None:
    """Allow one extra tap for a finished athlete after coach confirmation."""
    for athlete in session_state.athletes:
        if athlete.athlete_id == athlete_id:
            athlete.reopened_after_finish = True
            session_state.message = f"Reopened {athlete.name} for correction."
            return


def record_split(session_state, athlete_id: str, now: float | None = None, record_anyway: bool = False) -> SplitRecord | None:
    """Record a split for an athlete unless state guards block it."""
    clock = session_state.race_clock
    if clock.status != "running":
        session_state.message = "Athlete taps are only enabled while the race is running."
        return None

    current = time.perf_counter() if now is None else now
    last_tap_time = session_state.last_tap.get(athlete_id)
    if not record_anyway and last_tap_time is not None and current - last_tap_time < DUPLICATE_LOCKOUT_SECONDS:
        session_state.pending_duplicate = {"athlete_id": athlete_id, "recorded_at": current}
        session_state.message = "Duplicate tap ignored. Use Record Anyway to keep it."
        return None

    athlete = next((candidate for candidate in session_state.athletes if candidate.athlete_id == athlete_id), None)
    if athlete is None:
        session_state.message = "Athlete not found."
        return None
    if is_athlete_finished(session_state, athlete_id) and not athlete.reopened_after_finish:
        session_state.message = f"{athlete.name} is already finished. Reopen the athlete to record another split."
        return None

    session_state.split_sequence += 1
    split = build_split_record(
        split_id=str(uuid4()),
        athlete=athlete,
        existing_athlete_splits=athlete_splits(session_state, athlete_id),
        checkpoints=session_state.meet_config.checkpoints,
        elapsed_seconds=elapsed_seconds(clock, current),
        race_distance_meters=session_state.meet_config.race_distance_meters,
        sequence=session_state.split_sequence,
    )
    if split is None:
        session_state.message = f"{athlete.name} has no remaining checkpoints."
        athlete.reopened_after_finish = False
        return None
    session_state.splits.append(split)
    athlete.reopened_after_finish = False
    session_state.last_tap[athlete_id] = current
    session_state.pending_duplicate = None
    session_state.message = f"Recorded {athlete.name} at {split.checkpoint_label}."
    return split


def undo_last_split(session_state) -> SplitRecord | None:
    """Remove the latest split and recalculate that athlete's status."""
    if not session_state.splits:
        session_state.message = "No split to undo."
        return None
    last_split = max(session_state.splits, key=lambda split: split.sequence)
    session_state.splits = [split for split in session_state.splits if split.split_id != last_split.split_id]
    refresh_all_splits(session_state)
    session_state.message = f"Undid {last_split.athlete_name} at {last_split.checkpoint_label}."
    return last_split


def replace_setup(session_state, config: MeetConfig, athletes: list[Athlete]) -> None:
    """Replace saved setup while preserving existing splits when possible."""
    session_state.meet_config = config
    session_state.athletes = athletes
    session_state.setup_saved = True
    refresh_all_splits(session_state)


def refresh_all_splits(session_state) -> None:
    """Recalculate derived fields for all athletes using current setup."""
    updated: list[SplitRecord] = []
    for athlete in session_state.athletes:
        updated.extend(
            recalculate_athlete_splits(
                athlete_splits(session_state, athlete.athlete_id),
                athlete,
                session_state.meet_config.checkpoints,
                session_state.meet_config.race_distance_meters,
            )
        )
    session_state.splits = sorted(updated, key=lambda split: split.sequence)


def clear_setup(session_state) -> None:
    """Clear setup and race data after confirmation from the UI."""
    session_state.meet_config = MeetConfig()
    session_state.athletes = []
    reset_race(session_state)
    session_state.setup_saved = False
    session_state.message = "Setup cleared."


def initialize_persistence_state(session_state) -> None:
    """Initialize selected persisted meet/race session keys."""
    session_state.setdefault("selected_meet_id", None)
    session_state.setdefault("selected_race_id", None)
    session_state.setdefault("repository_result", None)
    session_state.setdefault("repository", None)
    session_state.setdefault("active_race_session_id", None)
    session_state.setdefault("timing_restored_for_race_id", None)


def load_race_into_setup(session_state, meet, race) -> None:
    """Load persisted meet/race metadata into the existing setup workflow.

    Phase 1 intentionally does not persist athletes, checkpoints, splits, or results.
    """
    from split_tracker.calculations import generate_checkpoints
    from split_tracker.formatting import format_distance
    from split_tracker.models import MeetConfig

    checkpoints = generate_checkpoints(
        race_distance_meters=race.distance_meters,
        mode=race.checkpoint_mode or "Standard laps",
        interval_meters=400.0 if race.course_type == "Track" else 1609.344,
    )
    session_state.selected_meet_id = meet.id
    session_state.selected_race_id = race.id
    session_state.meet_config = MeetConfig(
        meet_name=meet.name,
        race_name=race.name,
        course_type=race.course_type or "Cross Country",
        race_distance_meters=race.distance_meters,
        race_distance_label=format_distance(race.distance_meters),
        checkpoint_mode=race.checkpoint_mode or "Standard laps",
        checkpoint_interval_meters=400.0 if race.course_type == "Track" else 1609.344,
        checkpoints=checkpoints,
    )
    session_state.setup_saved = True
    session_state.message = "Loaded saved race setup. Roster, checkpoints, and live results still use session state in this phase."
