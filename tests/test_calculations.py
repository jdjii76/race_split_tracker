from split_tracker.calculations import (
    average_pace,
    build_split_record,
    cumulative_distance,
    projected_finish,
    segment_split,
    target_pace_variance,
)
from split_tracker.models import Athlete


def test_segment_split_first_and_later_split():
    assert segment_split(None, 75.0) == 75.0
    assert segment_split(75.0, 150.5) == 75.5


def test_segment_split_never_negative():
    assert segment_split(100.0, 90.0) == 0.0


def test_average_pace_and_projected_finish():
    assert average_pace(600.0, 2.0) == 300.0
    assert projected_finish(600.0, 2.0, 3.0) == 900.0


def test_average_pace_handles_zero_distance():
    assert average_pace(600.0, 0.0) is None
    assert projected_finish(600.0, 0.0, 3.0) is None


def test_cumulative_distance_caps_at_race_distance():
    assert cumulative_distance(4, 1.0, 3.1) == 3.1


def test_target_pace_variance():
    assert target_pace_variance(310.0, 300.0) == 10.0
    assert target_pace_variance(None, 300.0) is None
    assert target_pace_variance(310.0, None) is None


def test_build_split_record_derives_fields():
    athlete = Athlete(name="Sam Runner", bib_number="12", target_pace_seconds_per_mile=300.0, athlete_id="a1")
    first = build_split_record(
        split_id="s1",
        athlete=athlete,
        existing_athlete_splits=[],
        elapsed_seconds=305.0,
        checkpoint_distance_miles=1.0,
        race_distance_miles=2.0,
        sequence=1,
    )
    second = build_split_record(
        split_id="s2",
        athlete=athlete,
        existing_athlete_splits=[first],
        elapsed_seconds=620.0,
        checkpoint_distance_miles=1.0,
        race_distance_miles=2.0,
        sequence=2,
    )

    assert first.checkpoint_number == 1
    assert first.segment_split_seconds == 305.0
    assert first.target_variance_seconds_per_mile == 5.0
    assert second.checkpoint_number == 2
    assert second.segment_split_seconds == 315.0
    assert second.projected_finish_seconds == 620.0
