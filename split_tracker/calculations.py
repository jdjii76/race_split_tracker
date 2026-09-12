"""Pure calculation helpers for Race Split Tracker."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from math import isfinite
from typing import TypeVar

from split_tracker.formatting import METERS_PER_MILE, format_distance, parse_distance_to_meters
from split_tracker.models import Athlete, Checkpoint, SplitRecord


CheckpointKey = TypeVar("CheckpointKey")


@dataclass(frozen=True)
class CombinedInterval:
    """Known elapsed interval spanning at least one unavailable checkpoint."""

    from_checkpoint: str
    to_checkpoint: str
    value_seconds: float
    missing_segment_count: int
    estimation_unavailable_reason: str | None = None


@dataclass(frozen=True)
class EstimatedSegment:
    """Distance-proportional interpretation, explicitly not canonical timing."""

    from_checkpoint: str
    to_checkpoint: str
    distance_meters: float
    value_seconds: float
    source_gap_start: str
    source_gap_end: str
    source_type: str = "estimated"
    is_estimated: bool = True


@dataclass(frozen=True)
class GapEstimates:
    combined_intervals: tuple[CombinedInterval, ...]
    estimated_segments: tuple[EstimatedSegment, ...]


def derive_segment_splits(
    cumulative_splits: Mapping[CheckpointKey, float | None],
    checkpoint_order: Iterable[CheckpointKey],
) -> dict[CheckpointKey, float | None]:
    """Derive individual segment durations from canonical elapsed times.

    A segment is available only when its own cumulative time and the immediately
    preceding checkpoint's cumulative time are available.  This deliberately
    avoids presenting a multi-segment interval as one checkpoint's split after
    a missing checkpoint.  Invalid or non-increasing canonical values are left
    untouched and produce an unavailable display value.
    """
    segments: dict[CheckpointKey, float | None] = {}
    previous: float | None = 0.0
    for key in checkpoint_order:
        raw = cumulative_splits.get(key)
        current = float(raw) if raw is not None else None
        segment = current - previous if current is not None and previous is not None else None
        segments[key] = segment if segment is not None and segment > 0 else None
        previous = current
    return segments


def derive_gap_estimates(
    checkpoints: Iterable[Checkpoint],
    cumulative_values: Mapping[int, float | None],
    *,
    include_race_start: bool = True,
) -> GapEstimates:
    """Estimate only segments bounded by canonical cumulative observations.

    The known combined interval remains distinct from its distance-proportional
    estimates. Nothing returned by this helper is suitable for canonical rank,
    result, or recorded-pace calculations.
    """
    ordered = list(checkpoints)
    boundaries: list[tuple[int, str, float | None, float]] = []
    if include_race_start:
        boundaries.append((-1, "Start", 0.0, 0.0))
    for index, checkpoint in enumerate(ordered):
        raw = cumulative_values.get(checkpoint.number)
        numeric = float(raw) if raw is not None else None
        elapsed = numeric if numeric is not None and isfinite(numeric) and numeric > 0 else None
        if elapsed is not None:
            boundaries.append((index, checkpoint.label, checkpoint.distance_meters, elapsed))

    combined: list[CombinedInterval] = []
    estimated: list[EstimatedSegment] = []
    for left, right in zip(boundaries, boundaries[1:]):
        left_index, left_label, left_distance, left_elapsed = left
        right_index, right_label, _, right_elapsed = right
        if right_index - left_index <= 1:
            continue
        interval_seconds = right_elapsed - left_elapsed
        if interval_seconds <= 0:
            continue
        span = ordered[left_index + 1:right_index + 1]
        prior_distance = left_distance
        segment_distances: list[float] = []
        invalid_distance = prior_distance is None
        for checkpoint in span:
            distance = checkpoint.distance_meters
            if (distance is None or prior_distance is None
                    or not isfinite(float(distance)) or not isfinite(float(prior_distance))
                    or float(distance) <= float(prior_distance)):
                invalid_distance = True
                break
            segment_distances.append(float(distance) - float(prior_distance))
            prior_distance = float(distance)
        reason = "Checkpoint distances are unavailable or non-increasing." if invalid_distance else None
        combined.append(CombinedInterval(
            left_label, right_label, interval_seconds, len(span), reason,
        ))
        if invalid_distance:
            continue
        total_distance = sum(segment_distances)
        allocated = 0.0
        prior_label = left_label
        for offset, (checkpoint, distance) in enumerate(zip(span, segment_distances)):
            value = (interval_seconds - allocated if offset == len(span) - 1
                     else interval_seconds * distance / total_distance)
            estimated.append(EstimatedSegment(
                prior_label, checkpoint.label, distance, value,
                left_label, right_label,
            ))
            allocated += value
            prior_label = checkpoint.label
    return GapEstimates(tuple(combined), tuple(estimated))

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
    """Return the first persisted checkpoint identity not actively completed."""
    completed = {split.checkpoint_number for split in existing_athlete_splits}
    return next((checkpoint for checkpoint in checkpoints if checkpoint.number not in completed), None)


def athlete_finished(splits: Iterable[SplitRecord], checkpoints: list[Checkpoint]) -> bool:
    """Return whether an athlete has reached the finish checkpoint."""
    completed = {split.checkpoint_number for split in splits}
    finish = next((checkpoint for checkpoint in checkpoints if checkpoint.is_finish), None)
    return finish is not None and finish.number in completed


def build_split_record(
    *,
    split_id: str,
    athlete: Athlete,
    existing_athlete_splits: Iterable[SplitRecord],
    checkpoints: list[Checkpoint],
    elapsed_seconds: float,
    race_distance_meters: float,
    sequence: int,
    checkpoint_number: int | None = None,
) -> SplitRecord | None:
    """Build a derived split record for an athlete at the given elapsed time."""
    previous_splits = sorted(existing_athlete_splits, key=lambda split: split.sequence)
    checkpoint = (
        next((item for item in checkpoints if item.number == checkpoint_number), None)
        if checkpoint_number is not None
        else next_checkpoint(previous_splits, checkpoints)
    )
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
    checkpoints_by_number = {checkpoint.number: checkpoint for checkpoint in checkpoints}
    seen: set[int] = set()
    for split in ordered:
        checkpoint = checkpoints_by_number.get(split.checkpoint_number)
        if checkpoint is None or checkpoint.number in seen:
            continue
        seen.add(checkpoint.number)
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
