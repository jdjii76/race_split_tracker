from datetime import datetime, timezone
from pathlib import Path

import pytest

from split_tracker.models import Checkpoint
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, RepositoryError, SplitEvent


def _race(repo):
    meet = repo.create_meet(Meet(name="Invitational"))
    race = repo.create_race(Race(meet_id=meet.id, name="Varsity", distance_meters=5000))
    session = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=datetime.now(timezone.utc)))
    repo.create_race_session_checkpoints(session.id, [Checkpoint(1, "Mile 1", 1609), Checkpoint(2, "Finish", 5000, is_finish=True)])
    return race, session


def test_finish_assignment_can_reset_without_replacing_setup_or_events():
    repo = InMemoryRaceRepository()
    race, session = _race(repo)
    repo.assign_timer_station(session.id, 2, "finish-device")
    event = repo.create_split_event(SplitEvent(race_session_id=session.id, athlete_id="a", athlete_name="A", checkpoint_number=1, checkpoint_label="Mile 1", elapsed_seconds=300, event_order=1))
    checkpoints = repo.list_race_session_checkpoints(session.id)

    reset = repo.reset_race_start(session.id, finish_checkpoint_number=2, device_id="finish-device")

    assert reset.id == session.id and reset.race_id == race.id
    assert reset.status == "ready" and reset.started_at is None and reset.paused_at is None and reset.ended_at is None
    assert reset.elapsed_offset_seconds == 0
    assert repo.list_race_session_checkpoints(session.id) == checkpoints
    assert repo.list_all_split_events(session.id) == [event]
    assert repo.timer_station_assignments[(session.id, "finish-device")] == 2


@pytest.mark.parametrize("checkpoint", [1, 3])
def test_checkpoint_assignment_cannot_reset(checkpoint):
    repo = InMemoryRaceRepository()
    _, session = _race(repo)
    repo.assign_timer_station(session.id, 1, f"device-{checkpoint}")
    with pytest.raises(RepositoryError, match="Finish Line"):
        repo.reset_race_start(session.id, finish_checkpoint_number=checkpoint, device_id=f"device-{checkpoint}")


def test_paused_reset_can_start_same_session_again():
    repo = InMemoryRaceRepository()
    _, session = _race(repo)
    paused = repo.transition_race_session(session.id, "pause")
    reset = repo.reset_race_start(paused.id)  # manager path in the local repository
    restarted = repo.start_race_session(reset.id, datetime.now(timezone.utc))
    assert restarted.id == session.id and restarted.status == "running"


def test_migration_enforces_authenticated_finish_assignment_and_preserves_events():
    sql = (Path(__file__).parents[1] / "supabase/migrations/036_reset_race_start.sql").read_text()
    for contract in ("auth.uid() is null", "timer_station_assignments", "c.is_finish=true", "for update", "status='ready'", "started_at=null", "elapsed_offset_seconds=0", "race_start_reset"):
        assert contract in sql.lower()
    assert "delete from public.split_events" not in sql.lower()


def test_finish_ui_has_state_controls_warning_and_queue_preservation_copy():
    source = (Path(__file__).parents[1] / "pages/live_timing.py").read_text()
    assert 'lifecycle_label = "PAUSE" if clock.status == "running" else "RESUME"' in source
    assert 'secondary.button("RESET START"' in source
    assert "Timing data already exists for this race." in source
    assert "durable queue" in source
    assert "checkpoint is None or not checkpoint.is_finish" in source
