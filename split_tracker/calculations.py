"""Pure calculation helpers for Race Split Tracker."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from split_tracker.formatting import METERS_PER_MILE, format_distance, parse_distance_to_meters
from split_tracker.models import Athlete, Checkpoint, SplitRecord

TRACK_DISTANCE_PRESETS = {
    "100 m": 100.0,
    "200 m": 200.0,
    "400 m": 400.0,
    "800 m": 800.0,
    "1500 m": 1500.0,
    "1600 m": 1600.0,
    "1 mile": METERS_PER_MILE,
    "3000 m": 3000.0,
    "3200 m": 3200.0,
    "5000 m": 5000.0,
    "10,000 m": 10000.0,
}

XC_DISTANCE_PRESETS = {
    "1 mile": METERS_PER_MILE,
    "2 miles": METERS_PER_MILE * 2,
    "3 miles": METERS_PER_MILE * 3,
    "5K": 5000.0,
    "8K": 8000.0,
    "10K": 10000.0,
}


def race_distance_from_preset(course_type: str, preset: str, custom_meters: float | None = None) -> float:
    """Return a race distance in meters from a course-specific preset."""
    if preset == "Custom":
        if custom_meters is None or custom_meters <= 0:
            raise ValueError("Custom distance must be greater than zero.")
        return float(custom_meters)
    presets = TRACK_DISTANCE_PRESETS if course_type == "Track" else XC_DISTANCE_PRESETS
    return presets[preset]


def segment_split(previous_cumulative_seconds: float | None, current_cumulative_seconds: float) -> float:
    """Return segment split seconds for a new cumulative time."""
    if previous_cumulative_seconds is None:
        return current_cumulative_seconds
    return max(0.0, current_cumulative_seconds - previous_cumulative_seconds)


def average_pace(cumulative_time_seconds: float, cumulative_distance_meters: float) -> float | None:
    """Return average seconds per mile for elapsed time and distance in meters."""
    if cumulative_distance_meters <= 0:
        return None
    return cumulative_time_seconds / (cumulative_distance_meters / METERS_PER_MILE)


def projected_finish(
    cumulative_time_seconds: float,
    cumulative_distance_meters: float,
    race_distance_meters: float,
) -> float | None:
    """Project finish time from current average pace and meter distances."""
    if cumulative_distance_meters <= 0 or race_distance_meters <= 0:
        return None
    return cumulative_time_seconds * (race_distance_meters / cumulative_distance_meters)


def target_variance(
    *,
    actual_pace_seconds_per_mile: float | None,
    projected_finish_seconds: float | None,
    target_pace_seconds_per_mile: float | None,
    target_finish_time_seconds: float | None,
) -> float | None:
    """Return pace variance when available, otherwise projected finish variance."""
    if actual_pace_seconds_per_mile is not None and target_pace_seconds_per_mile is not None:
        return actual_pace_seconds_per_mile - target_pace_seconds_per_mile
    if projected_finish_seconds is not None and target_finish_time_seconds is not None:
        return projected_finish_seconds - target_finish_time_seconds
    return None


def _dedupe_and_finish(distances: list[float], race_distance_meters: float) -> list[float]:
    usable = sorted({round(distance, 3) for distance in distances if 0 < distance < race_distance_meters})
    usable.append(round(race_distance_meters, 3))
    return usable


def generate_checkpoints(
    *,
    race_distance_meters: float,
    mode: str,
    interval_meters: float | None = None,
    custom_checkpoint_text: str = "",
) -> list[Checkpoint]:
    """Generate ordered checkpoints and always include the finish."""
    if race_distance_meters <= 0:
        return []
    distances: list[float] = []
    if mode in {"Standard laps", "Fixed interval"}:
        interval = interval_meters or 400.0
        if interval <= 0:
            raise ValueError("Checkpoint interval must be greater than zero.")
        marker = interval
        while marker < race_distance_meters:
            distances.append(marker)
            marker += interval
    elif mode == "Custom checkpoints":
        parts = [part.strip() for part in custom_checkpoint_text.replace("\n", ",").split(",")]
        for part in parts:
            if not part:
                continue
            if part.lower() == "finish":
                distances.append(race_distance_meters)
                continue
            parsed = parse_distance_to_meters(part)
            if parsed is None:
                raise ValueError(f"Could not parse checkpoint distance: {part}")
            distances.append(parsed)
    else:
        raise ValueError(f"Unknown checkpoint mode: {mode}")

    final_distances = _dedupe_and_finish(distances, race_distance_meters)
    return [
        Checkpoint(
            number=index,
            label="Finish" if abs(distance - race_distance_meters) < 0.01 else format_distance(distance),
            distance_meters=distance,
            is_finish=abs(distance - race_distance_meters) < 0.01,
        )
        for index, distance in enumerate(final_distances, start=1)
    ]


def next_checkpoint(existing_athlete_splits: Iterable[SplitRecord], checkpoints: list[Checkpoint]) -> Checkpoint | None:
    """Return the next checkpoint for an athlete, or None after finish."""
    count = len(list(existing_athlete_splits))
    if count >= len(checkpoints):
        return None
    return checkpoints[count]


def athlete_finished(splits: Iterable[SplitRecord], checkpoints: list[Checkpoint]) -> bool:
    """Return whether an athlete has reached the finish checkpoint."""
    ordered = sorted(splits, key=lambda split: split.sequence)
    return bool(ordered and ordered[-1].is_finish and len(ordered) >= len(checkpoints))


def build_split_record(
    *,
    split_id: str,
    athlete: Athlete,
    existing_athlete_splits: Iterable[SplitRecord],
    checkpoints: list[Checkpoint],
    elapsed_seconds: float,
    race_distance_meters: float,
    sequence: int,
) -> SplitRecord | None:
    """Build a derived split record for an athlete at the given elapsed time."""
    previous_splits = sorted(existing_athlete_splits, key=lambda split: split.sequence)
    checkpoint = next_checkpoint(previous_splits, checkpoints)
    if checkpoint is None:
        return None
    previous_cumulative = previous_splits[-1].cumulative_time_seconds if previous_splits else None
    segment = segment_split(previous_cumulative, elapsed_seconds)
    avg_pace = average_pace(elapsed_seconds, checkpoint.distance_meters)
    projection = projected_finish(elapsed_seconds, checkpoint.distance_meters, race_distance_meters)
    variance = target_variance(
        actual_pace_seconds_per_mile=avg_pace,
        projected_finish_seconds=projection,
        target_pace_seconds_per_mile=athlete.target_pace_seconds_per_mile,
        target_finish_time_seconds=athlete.target_finish_time_seconds,
    )
    return SplitRecord(
        split_id=split_id,
        athlete_id=athlete.athlete_id,
        athlete_name=athlete.name,
        bib_number=athlete.bib_number,
        checkpoint_number=checkpoint.number,
        checkpoint_label=checkpoint.label,
        checkpoint_distance_meters=checkpoint.distance_meters,
        cumulative_time_seconds=elapsed_seconds,
        segment_split_seconds=segment,
        average_pace_seconds_per_mile=avg_pace,
        projected_finish_seconds=projection,
        target_variance_seconds=variance,
        is_finish=checkpoint.is_finish,
        sequence=sequence,
    )


def recalculate_athlete_splits(
    splits: Iterable[SplitRecord],
    athlete: Athlete,
    checkpoints: list[Checkpoint],
    race_distance_meters: float,
) -> list[SplitRecord]:
    """Recalculate derived values for one athlete after edits or deletes."""
    recalculated: list[SplitRecord] = []
    ordered = sorted(splits, key=lambda split: split.sequence)
    previous_cumulative: float | None = None
    for index, split in enumerate(ordered[: len(checkpoints)]):
        checkpoint = checkpoints[index]
        segment = segment_split(previous_cumulative, split.cumulative_time_seconds)
        avg_pace = average_pace(split.cumulative_time_seconds, checkpoint.distance_meters)
        projection = projected_finish(split.cumulative_time_seconds, checkpoint.distance_meters, race_distance_meters)
        variance = target_variance(
            actual_pace_seconds_per_mile=avg_pace,
            projected_finish_seconds=projection,
            target_pace_seconds_per_mile=athlete.target_pace_seconds_per_mile,
            target_finish_time_seconds=athlete.target_finish_time_seconds,
        )
        recalculated.append(
            replace(
                split,
                athlete_name=athlete.name,
                bib_number=athlete.bib_number,
                checkpoint_number=checkpoint.number,
                checkpoint_label=checkpoint.label,
                checkpoint_distance_meters=checkpoint.distance_meters,
                segment_split_seconds=segment,
                average_pace_seconds_per_mile=avg_pace,
                projected_finish_seconds=projection,
                target_variance_seconds=variance,
                is_finish=checkpoint.is_finish,
            )
        )
        previous_cumulative = split.cumulative_time_seconds
    return recalculated
