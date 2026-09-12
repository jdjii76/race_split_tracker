"""Pure coach-facing gap estimation tests."""
import pytest

from split_tracker.calculations import derive_gap_estimates
from split_tracker.models import Checkpoint


FIVE_K = [
    Checkpoint(1, "Mile 1", 1609.344),
    Checkpoint(2, "Mile 2", 3218.688),
    Checkpoint(3, "Mile 3", 4828.032),
    Checkpoint(4, "Finish", 5000, True),
]


def test_one_missing_5k_checkpoint_uses_configured_short_finish_distance():
    result = derive_gap_estimates(FIVE_K, {1: 360, 2: 730, 3: None, 4: 1140})

    assert len(result.combined_intervals) == 1
    combined = result.combined_intervals[0]
    assert (combined.from_checkpoint, combined.to_checkpoint, combined.value_seconds) == ("Mile 2", "Finish", 410)
    assert [(item.from_checkpoint, item.to_checkpoint) for item in result.estimated_segments] == [
        ("Mile 2", "Mile 3"), ("Mile 3", "Finish")]
    assert result.estimated_segments[0].distance_meters == pytest.approx(1609.344)
    assert result.estimated_segments[1].distance_meters == pytest.approx(5000 - 4828.032)
    assert sum(item.value_seconds for item in result.estimated_segments) == pytest.approx(410)
    assert result.estimated_segments[0].is_estimated
    assert result.estimated_segments[0].source_type == "estimated"


def test_two_consecutive_missing_checkpoints_and_dynamic_count():
    result = derive_gap_estimates(FIVE_K, {1: 360, 2: None, 3: None, 4: 1230})

    assert result.combined_intervals[0].value_seconds == 870
    assert len(result.estimated_segments) == 3
    assert sum(item.value_seconds for item in result.estimated_segments) == pytest.approx(870)


def test_missing_first_checkpoint_can_use_authoritative_race_start_zero():
    result = derive_gap_estimates(FIVE_K[:3], {1: None, 2: 730, 3: 1110})

    assert result.combined_intervals[0].from_checkpoint == "Start"
    assert result.combined_intervals[0].to_checkpoint == "Mile 2"
    assert [item.to_checkpoint for item in result.estimated_segments] == ["Mile 1", "Mile 2"]
    assert sum(item.value_seconds for item in result.estimated_segments[:2]) == pytest.approx(730)


def test_no_missing_or_unbounded_trailing_gap_produces_no_estimate():
    complete = derive_gap_estimates(FIVE_K, {1: 360, 2: 730, 3: 1100, 4: 1140})
    missing_finish = derive_gap_estimates(FIVE_K, {1: 360, 2: 730, 3: 1100, 4: None})
    assert complete.combined_intervals == complete.estimated_segments == ()
    assert missing_finish.combined_intervals == missing_finish.estimated_segments == ()


@pytest.mark.parametrize("checkpoints", [
    [Checkpoint(1, "One", 1000), Checkpoint(2, "Unknown", None), Checkpoint(3, "Three", 3000)],
    [Checkpoint(1, "One", 1000), Checkpoint(2, "Backwards", 900), Checkpoint(3, "Three", 3000)],
])
def test_invalid_distance_preserves_combined_interval_without_estimates(checkpoints):
    result = derive_gap_estimates(checkpoints, {1: 240, 2: None, 3: 800})
    assert result.combined_intervals[0].value_seconds == 560
    assert result.combined_intervals[0].estimation_unavailable_reason
    assert result.estimated_segments == ()


def test_nonpositive_combined_elapsed_is_not_presented_or_estimated():
    result = derive_gap_estimates(FIVE_K, {1: 360, 2: 730, 3: None, 4: 700})
    assert result.combined_intervals == result.estimated_segments == ()


def test_multiple_independent_gaps_have_separate_exact_allocations():
    checkpoints = [Checkpoint(i, f"C{i}", i * 1000) for i in range(1, 7)]
    result = derive_gap_estimates(checkpoints, {1: 200, 2: None, 3: 620, 4: 810, 5: None, 6: 1250})
    assert [(item.from_checkpoint, item.to_checkpoint) for item in result.combined_intervals] == [
        ("C1", "C3"), ("C4", "C6")]
    assert sum(item.value_seconds for item in result.estimated_segments
               if item.source_gap_start == "C1") == pytest.approx(420)
    assert sum(item.value_seconds for item in result.estimated_segments
               if item.source_gap_start == "C4") == pytest.approx(440)
