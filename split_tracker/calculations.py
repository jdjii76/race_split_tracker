"""Pure calculation helpers for Race Split Tracker."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from split_tracker.models import Athlete, SplitRecord


def checkpoint_number(previous_split_count: int) -> int:
    """Return the next checkpoint number for an athlete."""
    return previous_split_count + 1


def cumulative_distance(checkpoint: int, checkpoint_distance_miles: float, race_distance_miles: float) -> float:
    """Return the distance reached at a checkpoint, capped at race distance."""
    return min(checkpoint * checkpoint_distance_miles, race_distance_miles)


def segment_split(previous_cumulative_seconds: float | None, current_cumulative_seconds: float) -> float:
    """Return segment split seconds for a new cumulative time."""
    if previous_cumulative_seconds is None:
        return current_cumulative_seconds
    return max(0.0, current_cumulative_seconds - previous_cumulative_seconds)


def average_pace(cumulative_time_seconds: float, cumulative_distance_miles: float) -> float | None:
    """Return average seconds per mile for elapsed time and distance."""
    if cumulative_distance_miles <= 0:
        return None
    return cumulative_time_seconds / cumulative_distance_miles


def projected_finish(
    cumulative_time_seconds: float,
    cumulative_distance_miles: float,
    race_distance_miles: float,
) -> float | None:
    """Project finish time from current average pace."""
    pace = average_pace(cumulative_time_seconds, cumulative_distance_miles)
    if pace is None or race_distance_miles <= 0:
        return None
    return pace * race_distance_miles


def target_pace_variance(
    actual_pace_seconds_per_mile: float | None,
    target_pace_seconds_per_mile: float | None,
) -> float | None:
    """Return actual pace minus target pace in seconds per mile."""
    if actual_pace_seconds_per_mile is None or target_pace_seconds_per_mile is None:
        return None
    return actual_pace_seconds_per_mile - target_pace_seconds_per_mile


def build_split_record(
    *,
    split_id: str,
    athlete: Athlete,
    existing_athlete_splits: Iterable[SplitRecord],
    elapsed_seconds: float,
    checkpoint_distance_miles: float,
    race_distance_miles: float,
    sequence: int,
) -> SplitRecord:
    """Build a derived split record for an athlete at the given elapsed time."""
    previous_splits = sorted(existing_athlete_splits, key=lambda split: split.checkpoint_number)
    checkpoint = checkpoint_number(len(previous_splits))
    previous_cumulative = previous_splits[-1].cumulative_time_seconds if previous_splits else None
    distance = cumulative_distance(checkpoint, checkpoint_distance_miles, race_distance_miles)
    segment = segment_split(previous_cumulative, elapsed_seconds)
    avg_pace = average_pace(elapsed_seconds, distance)
    projection = projected_finish(elapsed_seconds, distance, race_distance_miles)
    variance = target_pace_variance(avg_pace, athlete.target_pace_seconds_per_mile)
    return SplitRecord(
        split_id=split_id,
        athlete_id=athlete.athlete_id,
        athlete_name=athlete.name,
        bib_number=athlete.bib_number,
        checkpoint_number=checkpoint,
        checkpoint_distance_miles=checkpoint_distance_miles,
        cumulative_distance_miles=distance,
        cumulative_time_seconds=elapsed_seconds,
        segment_split_seconds=segment,
        average_pace_seconds_per_mile=avg_pace,
        projected_finish_seconds=projection,
        target_variance_seconds_per_mile=variance,
        sequence=sequence,
    )


def recalculate_athlete_splits(
    splits: Iterable[SplitRecord],
    athlete: Athlete,
    checkpoint_distance_miles: float,
    race_distance_miles: float,
) -> list[SplitRecord]:
    """Recalculate derived values for one athlete after edits or deletes."""
    recalculated: list[SplitRecord] = []
    ordered = sorted(splits, key=lambda split: split.sequence)
    previous_cumulative: float | None = None
    for index, split in enumerate(ordered, start=1):
        distance = cumulative_distance(index, checkpoint_distance_miles, race_distance_miles)
        segment = segment_split(previous_cumulative, split.cumulative_time_seconds)
        avg_pace = average_pace(split.cumulative_time_seconds, distance)
        projection = projected_finish(split.cumulative_time_seconds, distance, race_distance_miles)
        variance = target_pace_variance(avg_pace, athlete.target_pace_seconds_per_mile)
        recalculated.append(
            replace(
                split,
                athlete_name=athlete.name,
                bib_number=athlete.bib_number,
                checkpoint_number=index,
                checkpoint_distance_miles=checkpoint_distance_miles,
                cumulative_distance_miles=distance,
                segment_split_seconds=segment,
                average_pace_seconds_per_mile=avg_pace,
                projected_finish_seconds=projection,
                target_variance_seconds_per_mile=variance,
            )
        )
        previous_cumulative = split.cumulative_time_seconds
    return recalculated
