"""Concurrency tests for server-authoritative race lifecycle transitions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from split_tracker.models import Athlete, Checkpoint
from split_tracker.repository import (
    InMemoryRaceRepository,
    Meet,
    Race,
    RaceSession,
    RepositoryError,
)


def _running_repository():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Lifecycle Test"))
    race = repo.create_race(Race(meet_id=meet.id, name="5K", distance_meters=5000))
    athlete = Athlete("Alex", athlete_id="athlete")
    repo.replace_race_athletes(race.id, [athlete])
    session = repo.create_race_session(
        RaceSession(
            race_id=race.id,
            status="running",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
    )
    repo.create_race_session_checkpoints(
        session.id, [Checkpoint(1, "Finish", 5000, True)]
    )
    return repo, session


def _attempt(repo, session_id, action):
    try:
        return repo.transition_race_session(session_id, action)
    except RepositoryError:
        return None


def test_repeated_pause_resume_and_complete_are_idempotent(monkeypatch):
    repo, session = _running_repository()
    pause_at = session.started_at + timedelta(seconds=20)
    resume_at = pause_at + timedelta(minutes=1)
    complete_at = resume_at + timedelta(seconds=30)
    times = iter([pause_at, resume_at, complete_at])
    monkeypatch.setattr("split_tracker.repository.utc_now", lambda: next(times))

    paused = repo.transition_race_session(session.id, "pause")
    paused_again = repo.transition_race_session(session.id, "pause")
    resumed = repo.transition_race_session(session.id, "resume")
    resumed_again = repo.transition_race_session(session.id, "resume")
    completed = repo.transition_race_session(session.id, "complete")
    completed_again = repo.transition_race_session(session.id, "complete")

    assert paused_again == paused
    assert paused.elapsed_offset_seconds == 20
    assert resumed_again == resumed
    assert resumed.started_at == resume_at
    assert completed_again == completed
    assert completed.elapsed_offset_seconds == 50
    assert completed.ended_at == complete_at


@pytest.mark.parametrize(
    ("first_action", "second_action", "initial_action", "final_status"),
    [
        ("pause", "complete", None, "completed"),
        ("resume", "complete", "pause", "completed"),
        ("cancel", "pause", None, "cancelled"),
        ("cancel", "resume", "pause", "cancelled"),
    ],
)
def test_conflicting_transitions_cannot_resurrect_terminal_state(
    first_action, second_action, initial_action, final_status
):
    repo, session = _running_repository()
    if initial_action:
        repo.transition_race_session(session.id, initial_action)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda action: _attempt(repo, session.id, action),
                [first_action, second_action],
            )
        )

    final = repo.get_race_session(session.id)
    assert final is not None
    assert final.status == final_status
    idempotent_action = "complete" if final_status == "completed" else "cancel"
    assert repo.transition_race_session(session.id, idempotent_action) == final
    rejected = (
        ("pause", "resume", "cancel")
        if final_status == "completed"
        else ("pause", "resume", "complete")
    )
    for stale_action in rejected:
        with pytest.raises(RepositoryError, match="Invalid race session transition"):
            repo.transition_race_session(session.id, stale_action)


def test_complete_and_split_share_lock_and_produce_valid_outcome():
    repo, session = _running_repository()

    def split():
        try:
            return repo.record_shared_split(
                session.id, "athlete", 1, "Coach", "split-request"
            )
        except RepositoryError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        split_result, complete_result = list(
            executor.map(
                lambda operation: operation(),
                [split, lambda: repo.transition_race_session(session.id, "complete")],
            )
        )

    assert complete_result.status == "completed"
    assert repo.get_race_session(session.id).status == "completed"
    assert len(repo.list_active_split_events(session.id)) in {0, 1}
    if split_result is not None:
        assert split_result.checkpoint_number == 1
    with pytest.raises(RepositoryError, match="not running"):
        repo.record_shared_split(session.id, "athlete", 1, "Coach", "after-end")


def test_ready_cancel_has_no_end_timestamp_and_preserves_snapshots():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Ready Cancellation"))
    race = repo.create_race(Race(meet_id=meet.id, name="5K", distance_meters=5000))
    ready = repo.create_race_session(RaceSession(race_id=race.id, status="ready"))
    checkpoints = [Checkpoint(1, "Finish", 5000, True)]
    repo.create_race_session_checkpoints(ready.id, checkpoints)

    cancelled = repo.transition_race_session(ready.id, "cancel")

    assert cancelled.status == "cancelled"
    assert cancelled.started_at is None
    assert cancelled.ended_at is None
    assert len(repo.list_race_session_checkpoints(ready.id)) == 1
