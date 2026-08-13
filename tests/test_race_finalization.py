"""Guarded finish, DNF, reopen, isolation, and final-results behavior."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from split_tracker.models import Athlete, Checkpoint, PermanentAthlete
from split_tracker.navigation import build_race_dashboard_summaries
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, RepositoryError, SplitEvent
from split_tracker.results import build_team_summary, printable_results_html, reconstruct_results


def finalization_fixture():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Finalization Meet"))
    race = repo.create_race(Race(meet_id=meet.id, name="Varsity", distance_meters=3200))
    athletes = [Athlete("Alex", athlete_id="a"), Athlete("Blair", athlete_id="b")]
    repo.replace_race_athletes(race.id, athletes)
    checkpoints = [Checkpoint(1, "Mile 1", 1609.344), Checkpoint(2, "Finish", 3200, True)]
    session = repo.create_race_session(RaceSession(
        race_id=race.id, status="running",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=20),
    ))
    repo.create_race_session_checkpoints(session.id, checkpoints)
    return repo, meet, race, session, athletes, checkpoints


def event(repo, session, athlete_id, checkpoint, elapsed, order, **kwargs):
    return repo.create_split_event(SplitEvent(
        race_session_id=session.id, athlete_id=athlete_id,
        athlete_name=athlete_id, checkpoint_number=checkpoint,
        checkpoint_label="Finish" if checkpoint == 2 else "Mile 1",
        elapsed_seconds=elapsed, event_order=order, **kwargs,
    ))


def test_unresolved_blocks_finish_then_finished_and_dnf_resolutions_complete():
    repo, _, _, session, _, _ = finalization_fixture()
    event(repo, session, "a", 1, 300, 1)
    event(repo, session, "a", 2, 620, 2)
    event(repo, session, "b", 1, 330, 3)

    with pytest.raises(RepositoryError, match="Resolve every"):
        repo.finalize_race_session(session.id)
    outcome = repo.set_race_athlete_dnf(session.id, "b", "Coach")
    with pytest.raises(RepositoryError, match="Reverse DNF"):
        repo.record_shared_split(session.id, "b", 2, "Other Coach", "stale-dnf-tap")
    completed = repo.finalize_race_session(session.id)

    assert outcome.status == "dnf"
    assert completed.status == "completed"
    assert len(repo.list_active_split_events(session.id)) == 3
    with pytest.raises(RepositoryError, match="not running"):
        repo.record_shared_split(session.id, "b", 2, "Coach", "after-finish")


def test_all_finished_completion_and_concurrent_finish_are_idempotent():
    repo, _, _, session, _, _ = finalization_fixture()
    for order, (athlete, checkpoint, elapsed) in enumerate([
        ("a", 1, 300), ("b", 1, 310), ("a", 2, 620), ("b", 2, 640)
    ], start=1):
        event(repo, session, athlete, checkpoint, elapsed, order)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repo.finalize_race_session(session.id), range(2)))

    assert results[0].id == results[1].id == session.id
    assert results[0].ended_at == results[1].ended_at
    assert repo.get_race_session(session.id).status == "completed"


def test_reopen_preserves_splits_corrections_and_dnf_and_allows_reversal():
    repo, _, _, session, _, _ = finalization_fixture()
    normal = event(repo, session, "a", 1, 300, 1)
    repo.invalidate_split_event(normal.id, session.id, "a", 1, "Coach")
    manual = event(repo, session, "a", 1, 295, 2, correction_type="manual")
    event(repo, session, "a", 2, 615, 3)
    repo.set_race_athlete_dnf(session.id, "b", "Coach")
    repo.finalize_race_session(session.id)

    with pytest.raises(RepositoryError, match="Reopen"):
        repo.invalidate_split_event(manual.id, session.id, "a", 1, "Coach")

    reopened = repo.reopen_race_session(session.id)

    assert reopened.id == session.id and reopened.status == "paused"
    assert len(repo.list_all_split_events(session.id)) == 4  # original + append-only void + active splits
    assert repo.list_race_athlete_outcomes(session.id)[0].athlete_id == "b"
    repo.invalidate_split_event(manual.id, session.id, "a", 1, "Coach")
    assert repo.clear_race_athlete_dnf(session.id, "b") is True
    assert repo.list_race_athlete_outcomes(session.id) == []


def test_dnf_is_session_scoped_uuid_based_and_never_changes_permanent_status():
    repo, meet, race_a, session_a, _, checkpoints = finalization_fixture()
    permanent = repo.create_athlete(PermanentAthlete(first_name="Jordan", last_name="Lee", status="active"))
    race_b = repo.create_race(Race(meet_id=meet.id, name="Girls", distance_meters=3200))
    same_name = Athlete("Alex", athlete_id="other-a")
    repo.replace_race_athletes(race_b.id, [same_name])
    session_b = repo.create_race_session(RaceSession(race_id=race_b.id, status="paused"))
    repo.create_race_session_checkpoints(session_b.id, checkpoints)

    repo.set_race_athlete_dnf(session_a.id, "a", "Coach A")

    assert repo.list_race_athlete_outcomes(session_b.id) == []
    assert repo.get_athlete(permanent.id).status == "active"
    assert repo.get_race_session(session_b.id).status == "paused"


def test_final_results_rank_finishers_then_explicit_dnf_with_partial_splits():
    repo, meet, race, session, athletes, checkpoints = finalization_fixture()
    event(repo, session, "a", 1, 300, 1)
    invalid = event(repo, session, "a", 2, 650, 2)
    repo.invalidate_split_event(invalid.id, session.id, "a", 2, "Coach")
    event(repo, session, "a", 2, 620, 3, correction_type="manual")
    event(repo, session, "b", 1, 330, 4)
    repo.set_race_athlete_dnf(session.id, "b", "Coach")
    completed = repo.finalize_race_session(session.id)

    rows = reconstruct_results(
        meet_name=meet.name, race_name=race.name, session=completed,
        athletes=athletes, checkpoints=checkpoints, race_distance_meters=3200,
        events=repo.list_all_split_events(session.id),
        outcomes=repo.list_race_athlete_outcomes(session.id),
    )

    assert [(row["Athlete"], row["Place"], row["Status"]) for row in rows] == [
        ("Alex", 1, "Finished"), ("Blair", "—", "DNF")
    ]
    assert rows[0]["Final Time"] == "10:20.00"
    assert rows[1]["Mile 1 Cumulative"] == "5:30.00"
    assert rows[1]["Final Time"] == "—"


def test_dashboard_moves_completed_and_reopened_session_between_categories():
    repo, _, race, session, _, _ = finalization_fixture()
    repo.set_race_athlete_dnf(session.id, "a", "Coach")
    repo.set_race_athlete_dnf(session.id, "b", "Coach")
    completed = repo.finalize_race_session(session.id)
    assert build_race_dashboard_summaries([race], [completed], {race.id: 2})[0].category == "completed"

    reopened = repo.reopen_race_session(session.id)
    assert build_race_dashboard_summaries([race], [reopened], {race.id: 2})[0].category == "running"


def test_team_summary_scores_top_five_and_printable_results_include_race_details():
    rows = [
        {"Place": place, "Athlete": f"Runner {place}", "Team": "KMHS", "Status": "Finished", "Final Time": f"20:{place:02d}", "Average Pace": "6:30", "Split Times": "6:30 / 13:00"}
        for place in range(1, 6)
    ] + [{"Place": "—", "Athlete": "Runner DNF", "Team": "KMHS", "Status": "DNF", "Final Time": "—", "Average Pace": "—", "Split Times": "7:00 / —"}]

    summary = build_team_summary(rows)
    printable = printable_results_html("County Meet", "Varsity Boys", rows)

    assert summary == [{"Team": "KMHS", "Finishers": 5, "DNF": 1, "Top 5 Score": 15, "First Finisher": "Runner 1"}]
    assert "County Meet" in printable and "Varsity Boys" in printable
    assert "Average pace" in printable and "Runner DNF" in printable


def test_provisional_session_can_be_corrected_then_finalized_and_retained():
    repo, _, _, session, _, _ = finalization_fixture()
    for order, (athlete, checkpoint, elapsed) in enumerate([
        ("a", 1, 300), ("b", 1, 310), ("a", 2, 620), ("b", 2, 640)
    ], start=1):
        event(repo, session, athlete, checkpoint, elapsed, order)
    provisional = repo.transition_race_session(session.id, "pause")
    finish = next(item for item in repo.list_active_split_events(session.id) if item.athlete_id == "b" and item.checkpoint_number == 2)
    repo.invalidate_split_event(finish.id, session.id, "b", 2, "Coach")
    repo.record_manual_split(session.id, "b", 2, 635, "Coach", "replacement-finish")

    completed = repo.finalize_race_session(session.id)

    assert provisional.status == "paused" and completed.status == "completed"
    assert len(repo.list_all_split_events(session.id)) == 6
    assert repo.get_race_session(session.id).ended_at is not None
