import pytest

from split_tracker.calculations import (
    average_pace,
    athlete_finished,
    build_split_record,
    derive_segment_splits,
    generate_checkpoints,
    race_distance_from_preset,
    segment_split,
    target_variance,
)


def test_derive_segment_splits_normal_precision_and_dynamic_counts():
    assert derive_segment_splits({1: 360, 2: 740, 3: 1130}, [1, 2, 3]) == {1: 360, 2: 380, 3: 390}
    derived = derive_segment_splits({1: 474.9, 2: 912.0, 3: 1362.0}, [1, 2, 3])
    assert derived[1] == 474.9
    assert round(derived[2], 10) == 437.1
    assert derived[3] == 450.0
    assert derive_segment_splits({1: 42.25}, [1]) == {1: 42.25}


def test_derive_segment_splits_does_not_infer_across_missing_or_invalid_values():
    assert derive_segment_splits({1: 360, 3: 1120}, [1, 2, 3]) == {1: 360, 2: None, 3: None}
    assert derive_segment_splits({2: 740, 3: 1120}, [1, 2, 3]) == {1: None, 2: None, 3: 380}
    assert derive_segment_splits({1: 360, 2: 350, 3: 1120}, [1, 2, 3]) == {1: 360, 2: None, 3: 770}
from split_tracker.formatting import METERS_PER_MILE
from split_tracker.models import Athlete


def test_race_distance_preset_conversion():
    assert race_distance_from_preset("Track", "400 m") == 400.0
    assert race_distance_from_preset("Track", "1 mile") == pytest.approx(METERS_PER_MILE)
    assert race_distance_from_preset("Cross Country", "5K") == 5000.0
    assert race_distance_from_preset("Cross Country", "Custom", 4200.0) == 4200.0


def test_checkpoint_generation_includes_finish_when_not_evenly_divisible():
    checkpoints = generate_checkpoints(race_distance_meters=5000.0, mode="Fixed interval", interval_meters=1609.344)
    assert [checkpoint.label for checkpoint in checkpoints][-1] == "Finish"
    assert checkpoints[-1].distance_meters == 5000.0
    assert checkpoints[-1].is_finish is True


def test_custom_checkpoint_generation():
    checkpoints = generate_checkpoints(
        race_distance_meters=5000.0,
        mode="Custom checkpoints",
        custom_checkpoint_text="0.5 mile, 1 mile, 2 mile, finish",
    )
    assert len(checkpoints) == 4
    assert checkpoints[0].distance_meters == pytest.approx(METERS_PER_MILE / 2)
    assert checkpoints[-1].is_finish


def test_segment_split_first_and_later_split():
    assert segment_split(None, 75.0) == 75.0
    assert segment_split(75.0, 150.5) == 75.5


def test_average_pace_uses_meter_distances():
    assert average_pace(300.0, METERS_PER_MILE) == pytest.approx(300.0)
    assert average_pace(600.0, 0.0) is None


def test_target_variance_prefers_pace_and_falls_back_to_finish():
    assert target_variance(
        actual_pace_seconds_per_mile=310.0,
        projected_finish_seconds=930.0,
        target_pace_seconds_per_mile=300.0,
        target_finish_time_seconds=900.0,
    ) == 10.0
    assert target_variance(
        actual_pace_seconds_per_mile=310.0,
        projected_finish_seconds=930.0,
        target_pace_seconds_per_mile=None,
        target_finish_time_seconds=900.0,
    ) == 30.0


def test_build_split_record_and_athlete_completion():
    athlete = Athlete(name="Sam", bib_number="12", target_pace_seconds_per_mile=300.0, athlete_id="a1")
    checkpoints = generate_checkpoints(race_distance_meters=800.0, mode="Fixed interval", interval_meters=400.0)
    first = build_split_record(
        split_id="s1",
        athlete=athlete,
        existing_athlete_splits=[],
        checkpoints=checkpoints,
        elapsed_seconds=70.0,
        race_distance_meters=800.0,
        sequence=1,
    )
    second = build_split_record(
        split_id="s2",
        athlete=athlete,
        existing_athlete_splits=[first],
        checkpoints=checkpoints,
        elapsed_seconds=150.0,
        race_distance_meters=800.0,
        sequence=2,
    )

    assert first is not None
    assert second is not None
    assert first.checkpoint_label == "400 m"
    assert second.is_finish
    assert second.segment_split_seconds == 80.0
    assert athlete_finished([first, second], checkpoints)
