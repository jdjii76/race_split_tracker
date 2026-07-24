"""Tests for persistent live timing sessions and split events."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from split_tracker.calculations import generate_checkpoints
from split_tracker.models import Athlete, MeetConfig, RaceClock
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, SplitEvent, _race_session_to_row, _split_event_to_row
from split_tracker.state import record_split, start_race
from split_tracker.timing_persistence import (
    persist_completion,
    persisted_elapsed_seconds,
    persist_pause,
    persist_resume,
    persist_split_record,
    race_clock_from_session,
    rebuild_splits_from_events,
    refresh_splits_from_repository,
    restore_timing_state,
)


class SessionState(SimpleNamespace):
    def setdefault(self, key, value):
        if not hasattr(self, key):
            setattr(self, key, value)
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)


def make_repo_and_session():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Creekside Invitational"))
    race = repo.create_race(Race(meet_id=meet.id, name="Boys JV", distance_meters=800.0, course_type="Track"))
    checkpoints = generate_checkpoints(race_distance_meters=800.0, mode="Fixed interval", interval_meters=400.0)
    session = SessionState(
        repository=repo,
        selected_race_id=race.id,
        active_race_session_id=None,
        meet_config=MeetConfig(meet_name=meet.name, race_name=race.name, course_type="Track", race_distance_meters=800.0, checkpoints=checkpoints),
        athletes=[Athlete(name="Alex", bib_number="7", athlete_id="a1")],
        splits=[],
        race_clock=RaceClock(),
        last_tap={},
        split_sequence=0,
        pending_duplicate=None,
        setup_saved=True,
        message="",
    )
    return repo, race, session


def test_race_session_creation_and_active_lookup():
    repo, race, _ = make_repo_and_session()
    created = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))

    assert repo.get_race_session(created.id) == created
    assert repo.get_active_or_latest_race_session_for_race(race.id) == created
    assert repo.list_race_sessions_for_race(race.id) == [created]


def test_pause_resume_and_completion_elapsed_persistence():
    repo, race, session = make_repo_and_session()
    started = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)))
    session.active_race_session_id = started.id

    paused = persist_pause(session, 75.5, now_utc=datetime(2026, 1, 1, 12, 1, 15, tzinfo=timezone.utc))
    resumed = persist_resume(session, now_utc=datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc))
    elapsed_after_resume = persisted_elapsed_seconds(resumed, datetime(2026, 1, 1, 12, 2, 10, tzinfo=timezone.utc))
    completed = persist_completion(session, 150.0, now_utc=datetime(2026, 1, 1, 12, 3, tzinfo=timezone.utc))

    assert paused.status == "paused"
    assert paused.elapsed_offset_seconds == 75.5
    assert resumed.status == "running"
    assert elapsed_after_resume == 85.5
    assert completed.status == "completed"
    assert completed.elapsed_offset_seconds == 150.0
    assert completed.ended_at is not None


def test_race_clock_restore_from_paused_and_running_session():
    running = RaceSession(race_id="race", status="running", started_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), elapsed_offset_seconds=20.0)
    paused = RaceSession(race_id="race", status="paused", paused_at=datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc), elapsed_offset_seconds=80.0)

    running_clock = race_clock_from_session(running, now_perf=500.0, now_utc=datetime(2026, 1, 1, 12, 0, 10, tzinfo=timezone.utc))
    paused_clock = race_clock_from_session(paused, now_perf=500.0)

    assert running_clock.status == "running"
    assert running_clock.start_perf_counter == 470.0
    assert paused_clock.status == "paused"
    assert paused_clock.pause_started_at == 500.0


def test_split_event_creation_ordering_soft_delete_and_restore_active_events():
    repo, race, _ = make_repo_and_session()
    race_session = repo.create_race_session(RaceSession(race_id=race.id, status="running"))
    later = repo.create_split_event(SplitEvent(race_session_id=race_session.id, athlete_id="a1", checkpoint_number=2, elapsed_seconds=150.0, event_order=2))
    earlier = repo.create_split_event(SplitEvent(race_session_id=race_session.id, athlete_id="a1", checkpoint_number=1, elapsed_seconds=75.0, event_order=1))

    assert repo.list_active_split_events(race_session.id) == [earlier, later]
    deleted = repo.soft_delete_split_event(later.id)
    assert deleted.is_deleted
    assert repo.list_active_split_events(race_session.id) == [earlier]
    restored = repo.restore_split_event(later.id)
    assert not restored.is_deleted
    assert repo.list_active_split_events(race_session.id) == [earlier, restored]


def test_rebuild_runner_progress_from_persisted_events():
    repo, race, session = make_repo_and_session()
    race_session = repo.create_race_session(RaceSession(race_id=race.id, status="running"))
    events = [
        SplitEvent(race_session_id=race_session.id, athlete_id="a1", athlete_name="Alex", bib_number="7", checkpoint_number=1, elapsed_seconds=70.0, event_order=1),
        SplitEvent(race_session_id=race_session.id, athlete_id="a1", athlete_name="Alex", bib_number="7", checkpoint_number=2, elapsed_seconds=150.0, event_order=2),
    ]

    splits = rebuild_splits_from_events(events=events, athletes=session.athletes, config=session.meet_config)

    assert [split.checkpoint_number for split in splits] == [1, 2]
    assert splits[1].segment_split_seconds == 80.0
    assert splits[1].is_finish


def test_refresh_recovery_restores_paused_state_and_excludes_deleted_events():
    repo, race, session = make_repo_and_session()
    race_session = repo.create_race_session(RaceSession(race_id=race.id, status="paused", elapsed_offset_seconds=88.0, paused_at=datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)))
    session.active_race_session_id = race_session.id
    kept = repo.create_split_event(SplitEvent(race_session_id=race_session.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=1, elapsed_seconds=70.0, event_order=1))
    deleted = repo.create_split_event(SplitEvent(race_session_id=race_session.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=2, elapsed_seconds=150.0, event_order=2, is_deleted=True))

    restored = restore_timing_state(session, now_perf=1000.0)

    assert restored == race_session
    assert session.race_clock.status == "paused"
    assert session.race_clock.pause_started_at == 1000.0
    assert [split.split_id for split in session.splits] == [kept.id]
    assert deleted.id not in [split.split_id for split in session.splits]


def test_persisted_split_record_roundtrip_uses_existing_calculation_logic():
    repo, race, session = make_repo_and_session()
    race_session = repo.create_race_session(RaceSession(race_id=race.id, status="running"))
    session.active_race_session_id = race_session.id
    start_race(session, now=100.0)
    split = record_split(session, "a1", now=170.0)

    event = persist_split_record(session, split)
    session.splits = []
    refresh_splits_from_repository(session)

    assert event.elapsed_seconds == 70.0
    assert session.splits[0].segment_split_seconds == 70.0
    assert session.splits[0].split_id == event.id


def test_supabase_payload_serialization_for_session_and_split_event():
    session = RaceSession(race_id="race", status="running", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), elapsed_offset_seconds=12.5)
    event = SplitEvent(race_session_id=session.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=1, elapsed_seconds=70.0, event_order=1)

    session_row = _race_session_to_row(session)
    event_row = _split_event_to_row(event)

    assert session_row["race_id"] == "race"
    assert session_row["elapsed_offset_seconds"] == 12.5
    assert event_row["athlete_id"] == "a1"
    assert event_row["event_order"] == 1
    assert event_row["is_deleted"] is False
