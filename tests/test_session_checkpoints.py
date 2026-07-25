"""Tests for persisted race-session checkpoint snapshots."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from split_tracker.calculations import generate_checkpoints
from split_tracker.models import Athlete, MeetConfig, RaceClock
from split_tracker.repository import (
    InMemoryRaceRepository,
    Meet,
    Race,
    RaceSession,
    RepositoryError,
    SplitEvent,
    _session_checkpoint_from_row,
    _session_checkpoint_to_row,
    SupabaseRaceRepository,
)
from split_tracker.results import reconstruct_results, summarize_sessions
from split_tracker.session_checkpoints import get_session_checkpoints, snapshots_to_checkpoints
from split_tracker.timing_persistence import persist_start, refresh_splits_from_repository


class Session(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


def make_repo_race_and_checkpoints():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Creekside Invitational"))
    race = repo.create_race(Race(meet_id=meet.id, name="Boys JV", distance_meters=800.0, course_type="Track"))
    checkpoints = generate_checkpoints(race_distance_meters=800.0, mode="Fixed interval", interval_meters=400.0)
    return repo, meet, race, checkpoints


def make_session_state(repo, race, checkpoints):
    return Session(
        repository=repo,
        selected_race_id=race.id,
        active_race_session_id=None,
        meet_config=MeetConfig(meet_name="Creekside", race_name=race.name, race_distance_meters=race.distance_meters, checkpoints=checkpoints),
        athletes=[Athlete(name="Alex", athlete_id="a1")],
        splits=[],
        race_clock=RaceClock(),
        last_tap={},
        split_sequence=0,
        pending_duplicate=None,
        setup_saved=True,
        message="",
    )


def test_persist_start_creates_ordered_checkpoint_snapshot_with_critical_fields():
    repo, _, race, checkpoints = make_repo_race_and_checkpoints()
    state = make_session_state(repo, race, checkpoints)

    session = persist_start(state, now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc))
    snapshots = repo.list_race_session_checkpoints(session.id)

    assert session.status == "running"
    assert [snapshot.checkpoint_sequence for snapshot in snapshots] == [1, 2]
    assert [snapshot.label for snapshot in snapshots] == ["400 m", "Finish"]
    assert [snapshot.distance_meters for snapshot in snapshots] == [400.0, 800.0]
    assert snapshots[-1].is_finish is True
    assert snapshots[-1].checkpoint_type == "finish"


def test_start_is_atomic_when_snapshot_creation_fails():
    class FailingRepo(InMemoryRaceRepository):
        def create_race_session_checkpoints(self, race_session_id, checkpoints):
            raise RepositoryError("snapshot failed")

    repo = FailingRepo()
    meet = repo.create_meet(Meet(name="Meet"))
    race = repo.create_race(Race(meet_id=meet.id, name="Race", distance_meters=800.0))
    state = make_session_state(repo, race, generate_checkpoints(race_distance_meters=800.0, mode="Fixed interval", interval_meters=400.0))

    with pytest.raises(RepositoryError):
        persist_start(state)

    assert repo.list_race_sessions_for_race(race.id) == []
    assert repo.race_session_checkpoints == {}


def test_checkpoint_snapshot_idempotency_does_not_duplicate_or_overwrite():
    repo, _, race, checkpoints = make_repo_race_and_checkpoints()
    session = repo.create_started_race_session_with_checkpoints(RaceSession(race_id=race.id, status="running"), checkpoints)
    first = repo.list_race_session_checkpoints(session.id)
    changed = generate_checkpoints(race_distance_meters=1600.0, mode="Fixed interval", interval_meters=400.0)

    second = repo.create_race_session_checkpoints(session.id, changed)

    assert [item.id for item in second] == [item.id for item in first]
    assert [item.distance_meters for item in second] == [400.0, 800.0]


def test_duplicate_checkpoint_sequence_rejected_for_same_session():
    repo, _, race, checkpoints = make_repo_race_and_checkpoints()
    session = repo.create_race_session(RaceSession(race_id=race.id, status="ready"))
    duplicate = [checkpoints[0], checkpoints[0]]

    with pytest.raises(RepositoryError):
        repo.create_race_session_checkpoints(session.id, duplicate)


def test_snapshot_is_authoritative_after_underlying_configuration_changes():
    repo, meet, race, checkpoints = make_repo_race_and_checkpoints()
    athletes = [Athlete(name="Alex", athlete_id="a1")]
    repo.replace_race_athletes(race.id, athletes)
    session = repo.create_started_race_session_with_checkpoints(RaceSession(race_id=race.id, status="completed"), checkpoints)
    repo.create_split_event(SplitEvent(race_session_id=session.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=1, elapsed_seconds=60.0, event_order=1))
    repo.create_split_event(SplitEvent(race_session_id=session.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=2, elapsed_seconds=130.0, event_order=2))
    changed_checkpoints = generate_checkpoints(race_distance_meters=1600.0, mode="Fixed interval", interval_meters=400.0)

    checkpoint_result = get_session_checkpoints(repo, session, changed_checkpoints)
    rows = reconstruct_results(meet_name=meet.name, race_name=race.name, session=session, athletes=athletes, checkpoints=checkpoint_result.checkpoints, race_distance_meters=race.distance_meters, events=repo.list_active_split_events(session.id))

    assert checkpoint_result.source == "snapshot"
    assert [checkpoint.label for checkpoint in checkpoint_result.checkpoints] == ["400 m", "Finish"]
    assert rows[0]["Status"] == "Finished"
    assert rows[0]["Finish Time"] == "2:10.00"
    assert "1600 m Split" not in rows[0]


def test_session_summary_uses_snapshot_finish_detection_after_config_changes():
    repo, _, race, checkpoints = make_repo_race_and_checkpoints()
    athletes = [Athlete(name="Alex", athlete_id="a1")]
    session = repo.create_started_race_session_with_checkpoints(RaceSession(race_id=race.id, status="completed", elapsed_offset_seconds=130.0), checkpoints)
    repo.create_split_event(SplitEvent(race_session_id=session.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=1, elapsed_seconds=60.0, event_order=1))
    repo.create_split_event(SplitEvent(race_session_id=session.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=2, elapsed_seconds=130.0, event_order=2))
    changed_checkpoints = generate_checkpoints(race_distance_meters=1600.0, mode="Fixed interval", interval_meters=400.0)

    summaries = summarize_sessions(repo, race_id=race.id, athletes=athletes, checkpoints=changed_checkpoints, race_distance_meters=1600.0)

    assert summaries[0].finished_athlete_count == 1


def test_refresh_splits_uses_persisted_snapshot_labels_and_distances():
    repo, _, race, checkpoints = make_repo_race_and_checkpoints()
    session = repo.create_started_race_session_with_checkpoints(RaceSession(race_id=race.id, status="running"), checkpoints)
    repo.create_split_event(SplitEvent(race_session_id=session.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=1, elapsed_seconds=60.0, event_order=1))
    state = make_session_state(repo, race, generate_checkpoints(race_distance_meters=1600.0, mode="Fixed interval", interval_meters=400.0))
    state.active_race_session_id = session.id

    refresh_splits_from_repository(state)

    assert [checkpoint.label for checkpoint in state.meet_config.checkpoints] == ["400 m", "Finish"]
    assert state.splits[0].checkpoint_distance_meters == 400.0


def test_deleting_race_session_cascades_checkpoint_snapshots():
    repo, _, race, checkpoints = make_repo_race_and_checkpoints()
    session = repo.create_started_race_session_with_checkpoints(RaceSession(race_id=race.id, status="running"), checkpoints)

    assert repo.list_race_session_checkpoints(session.id)
    assert repo.delete_race_session(session.id) is True
    assert repo.list_race_session_checkpoints(session.id) == []


def test_legacy_session_without_snapshot_uses_isolated_fallback_without_persisting():
    repo, _, race, checkpoints = make_repo_race_and_checkpoints()
    session = repo.create_race_session(RaceSession(race_id=race.id, status="completed"))

    result = get_session_checkpoints(repo, session, checkpoints)
    second = get_session_checkpoints(repo, session, checkpoints)

    assert result.source == "legacy_fallback"
    assert [checkpoint.label for checkpoint in result.checkpoints] == ["400 m", "Finish"]
    assert repo.list_race_session_checkpoints(session.id) == []
    assert second.source == "legacy_fallback"


def test_session_checkpoint_serialization_roundtrip():
    repo, _, race, checkpoints = make_repo_race_and_checkpoints()
    session = repo.create_started_race_session_with_checkpoints(RaceSession(race_id=race.id, status="running"), checkpoints)
    snapshot = repo.list_race_session_checkpoints(session.id)[0]

    row = _session_checkpoint_to_row(snapshot)
    restored = _session_checkpoint_from_row(row)
    converted = snapshots_to_checkpoints([restored])

    assert row["race_session_id"] == session.id
    assert row["checkpoint_sequence"] == 1
    assert restored.label == "400 m"
    assert converted[0].distance_meters == 400.0


def test_supabase_started_session_uses_transactional_rpc_payload():
    class Result:
        def __init__(self, data):
            self.data = data

    class Operation:
        def __init__(self, result):
            self.result = result

        def execute(self):
            return self.result

    class Client:
        def __init__(self):
            self.calls = []

        def rpc(self, name, params):
            self.calls.append((name, params))
            return Operation(
                Result(
                    [
                        {
                            "id": params["p_session_id"],
                            "race_id": params["p_race_id"],
                            "status": "running",
                            "started_at": params["p_started_at"],
                            "elapsed_offset_seconds": params["p_elapsed_offset_seconds"],
                        }
                    ]
                )
            )

    checkpoints = generate_checkpoints(race_distance_meters=800.0, mode="Fixed interval", interval_meters=400.0)
    client = Client()
    repo = SupabaseRaceRepository(client)
    session = RaceSession(race_id="race-1", status="running", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    saved = repo.create_started_race_session_with_checkpoints(session, checkpoints)

    assert saved.status == "running"
    assert client.calls[0][0] == "create_started_race_session_with_checkpoints"
    payload = client.calls[0][1]["p_checkpoints"]
    assert [item["checkpoint_sequence"] for item in payload] == [1, 2]
    assert payload[-1]["checkpoint_type"] == "finish"
