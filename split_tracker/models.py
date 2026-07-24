"""Data models for the Race Split Tracker prototype."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

CourseType = Literal["Track", "Cross Country"]
RaceStatus = Literal["not_started", "running", "paused", "ended"]
CheckpointMode = Literal["Standard laps", "Fixed interval", "Custom checkpoints"]


@dataclass
class Checkpoint:
    """A configured timing location measured from the start."""

    number: int
    label: str
    distance_meters: float
    is_finish: bool = False


@dataclass
class Athlete:
    """An athlete in the meet roster."""

    name: str
    bib_number: str = ""
    gender: str = ""
    grade: str = ""
    team: str = ""
    target_finish_time_seconds: float | None = None
    target_pace_seconds_per_mile: float | None = None
    group: str = ""
    display_order: int = 0
    active: bool = True
    athlete_id: str = field(default_factory=lambda: str(uuid4()))
    reopened_after_finish: bool = False


@dataclass
class MeetConfig:
    """Configuration for the active meet and race."""

    meet_name: str = ""
    race_name: str = ""
    course_type: CourseType = "Track"
    race_distance_meters: float = 5000.0
    race_distance_label: str = "5000 m"
    checkpoint_mode: CheckpointMode = "Standard laps"
    checkpoint_interval_meters: float = 400.0
    lap_length_meters: float = 400.0
    custom_checkpoint_text: str = ""
    checkpoints: list[Checkpoint] = field(default_factory=list)


@dataclass
class SplitRecord:
    """A recorded athlete split at a race checkpoint."""

    split_id: str
    athlete_id: str
    athlete_name: str
    bib_number: str
    checkpoint_number: int
    checkpoint_label: str
    checkpoint_distance_meters: float
    cumulative_time_seconds: float
    segment_split_seconds: float
    average_pace_seconds_per_mile: float | None
    projected_finish_seconds: float | None
    target_variance_seconds: float | None
    is_finish: bool
    sequence: int


@dataclass
class RaceClock:
    """State needed to compute active elapsed race time."""

    status: RaceStatus = "not_started"
    start_perf_counter: float | None = None
    pause_started_at: float | None = None
    paused_total_seconds: float = 0.0
    ended_elapsed_seconds: float | None = None
