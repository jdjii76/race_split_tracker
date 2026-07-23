"""Data models for the Race Split Tracker prototype."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

CourseType = Literal["Track", "Cross Country"]
RaceStatus = Literal["not_started", "running", "paused", "ended"]


@dataclass
class Athlete:
    """An athlete in the meet roster."""

    name: str
    bib_number: str = ""
    target_pace_seconds_per_mile: float | None = None
    athlete_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass
class MeetConfig:
    """Configuration for the active meet and race."""

    meet_name: str = ""
    race_name: str = ""
    course_type: CourseType = "Track"
    race_distance_miles: float = 3.1
    checkpoint_distance_miles: float = 1.0


@dataclass
class SplitRecord:
    """A recorded athlete split at a race checkpoint."""

    split_id: str
    athlete_id: str
    athlete_name: str
    bib_number: str
    checkpoint_number: int
    checkpoint_distance_miles: float
    cumulative_distance_miles: float
    cumulative_time_seconds: float
    segment_split_seconds: float
    average_pace_seconds_per_mile: float | None
    projected_finish_seconds: float | None
    target_variance_seconds_per_mile: float | None
    sequence: int


@dataclass
class RaceClock:
    """State needed to compute active elapsed race time."""

    status: RaceStatus = "not_started"
    start_perf_counter: float | None = None
    pause_started_at: float | None = None
    paused_total_seconds: float = 0.0
    ended_elapsed_seconds: float | None = None
