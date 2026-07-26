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
    persist_start,
    poll_shared_timing,
    race_clock_from_session,
    rebuild_splits_from_events,
    refresh_splits_from_repository,
    restore_timing_state,
    start_and_synchronize_shared_timing,
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


def test_shared_started_at_is_authoritative_during_synchronization():
    from split_tracker.timing_persistence import synchronize_shared_timing
    repo, race, session = make_repo_and_session()
    origin = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=origin))
    session.active_race_session_id = shared.id

    synchronize_shared_timing(session, now_perf=500.0, now_utc=datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc))

    assert session.race_clock.start_perf_counter == 470.0


def test_persist_split_immediately_reloads_authoritative_events():
    repo, race, session = make_repo_and_session()
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running"))
    session.active_race_session_id = shared.id
    session.timer_name = "Finish tablet"
    start_race(session, now=10.0)
    local = record_split(session, "a1", now=80.0)
    session.splits.append(replace(local, split_id="stale"))

    saved = persist_split_record(session, local)

    assert saved.recorded_by == "Finish tablet"
    assert [split.split_id for split in session.splits] == [saved.id]


def test_duplicate_active_checkpoint_is_non_destructive():
    import pytest
    from split_tracker.repository import RepositoryError
    repo, race, _ = make_repo_and_session()
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running"))
    first = SplitEvent(race_session_id=shared.id, athlete_id="a1", checkpoint_number=1, elapsed_seconds=10, event_order=1)
    repo.create_split_event(first)

    with pytest.raises(RepositoryError, match="already has an active split"):
        repo.create_split_event(replace(first, id="another", event_order=2))
    assert [event.id for event in repo.list_active_split_events(shared.id)] == [first.id]


def test_two_clients_observe_split_and_correction_after_reload():
    from split_tracker.timing_persistence import synchronize_shared_timing
    repo, race, first = make_repo_and_session()
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=datetime.now(timezone.utc)))
    first.active_race_session_id = shared.id
    second = SessionState(**vars(first).copy())
    second.splits = []
    event = repo.create_split_event(SplitEvent(race_session_id=shared.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=1, checkpoint_label="400 m", elapsed_seconds=70, event_order=1))

    synchronize_shared_timing(second)
    assert [split.split_id for split in second.splits] == [event.id]
    repo.soft_delete_split_event(event.id)
    synchronize_shared_timing(second)
    assert second.splits == []


def test_sync_database_failure_preserves_visible_state():
    import pytest
    from split_tracker.repository import RepositoryError
    from split_tracker.timing_persistence import synchronize_shared_timing
    repo, race, session = make_repo_and_session()
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running"))
    session.active_race_session_id = shared.id
    sentinel = object()
    session.splits = [sentinel]

    class FailingRepository:
        def get_race_session(self, _session_id):
            raise RepositoryError("temporary outage")

    session.repository = FailingRepository()
    with pytest.raises(RepositoryError, match="temporary outage"):
        synchronize_shared_timing(session)
    assert session.splits == [sentinel]


def test_waiting_client_observes_other_clients_authoritative_start():
    from split_tracker.timing_persistence import synchronize_shared_timing

    repo, race, client_a = make_repo_and_session()
    ready = repo.create_race_session(RaceSession(race_id=race.id, status="ready"))
    client_a.active_race_session_id = ready.id
    client_a.timer_name = "Starter"
    client_b = SessionState(**vars(client_a).copy())
    client_b.timer_name = "Finish tablet"
    original_start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    persist_start(client_a, now_perf=100.0, now_utc=original_start)
    observed = synchronize_shared_timing(
        client_b,
        now_perf=230.0,
        now_utc=datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc),
    )

    assert observed.id == ready.id
    assert observed.started_at == original_start
    assert client_b.active_race_session_id == ready.id
    assert client_b.race_clock.status == "running"
    assert client_b.race_clock.start_perf_counter == 200.0
    assert client_b.timer_name == "Finish tablet"


def test_nearly_simultaneous_starts_preserve_first_started_at():
    repo, race, first = make_repo_and_session()
    ready = repo.create_race_session(RaceSession(race_id=race.id, status="ready"))
    first.active_race_session_id = ready.id
    second = SessionState(**vars(first).copy())
    first_start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    later_attempt = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)

    started_by_first = persist_start(first, now_utc=first_start)
    observed_by_second = persist_start(second, now_utc=later_attempt)

    assert started_by_first.id == observed_by_second.id == ready.id
    assert started_by_first.started_at == observed_by_second.started_at == first_start
    assert repo.get_race_session(ready.id).started_at == first_start


def test_waiting_poll_failure_preserves_session_and_timer_identity():
    import pytest
    from split_tracker.repository import RepositoryError
    from split_tracker.timing_persistence import synchronize_shared_timing

    _, _, waiting = make_repo_and_session()
    waiting.active_race_session_id = "shared-session"
    waiting.timer_name = "Back stretch"

    class FailingRepository:
        def get_race_session(self, _session_id):
            raise RepositoryError("temporary polling failure")

    waiting.repository = FailingRepository()
    with pytest.raises(RepositoryError, match="temporary polling failure"):
        synchronize_shared_timing(waiting)

    assert waiting.active_race_session_id == "shared-session"
    assert waiting.selected_race_id
    assert waiting.timer_name == "Back stretch"


def test_shared_progression_converges_across_clients_with_undo_correction_and_finish():
    import pytest
    from split_tracker.calculations import athlete_finished, next_checkpoint
    from split_tracker.models import Checkpoint
    from split_tracker.repository import RepositoryError
    from split_tracker.timing_persistence import synchronize_shared_timing

    repo, race, client_a = make_repo_and_session()
    custom = [
        Checkpoint(number=10, label="Creek", distance_meters=1000),
        Checkpoint(number=30, label="Hill", distance_meters=2000),
        Checkpoint(number=90, label="Finish", distance_meters=3000, is_finish=True),
    ]
    client_a.meet_config.checkpoints = custom
    client_a.meet_config.race_distance_meters = 3000
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=datetime.now(timezone.utc)))
    repo.create_race_session_checkpoints(shared.id, custom)
    client_a.active_race_session_id = shared.id
    client_b = SessionState(**vars(client_a).copy())
    client_b.splits = []

    mile_one = repo.create_split_event(SplitEvent(race_session_id=shared.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=10, elapsed_seconds=100, event_order=1))
    synchronize_shared_timing(client_b)
    assert next_checkpoint(client_b.splits, client_b.meet_config.checkpoints).number == 30

    mile_two = repo.create_split_event(SplitEvent(race_session_id=shared.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=30, elapsed_seconds=210, event_order=2))
    synchronize_shared_timing(client_a)
    assert next_checkpoint(client_a.splits, client_a.meet_config.checkpoints).number == 90

    # A timing-only correction retains checkpoint identity and cannot advance progress.
    repo.split_events[mile_two.id] = replace(repo.split_events[mile_two.id], elapsed_seconds=205)
    synchronize_shared_timing(client_a)
    assert next_checkpoint(client_a.splits, client_a.meet_config.checkpoints).number == 90

    with pytest.raises(RepositoryError, match="already has an active split"):
        repo.create_split_event(replace(mile_two, id="duplicate", event_order=3))
    synchronize_shared_timing(client_b)
    assert next_checkpoint(client_b.splits, client_b.meet_config.checkpoints).number == 90

    repo.soft_delete_split_event(mile_two.id)
    synchronize_shared_timing(client_b)
    assert next_checkpoint(client_b.splits, client_b.meet_config.checkpoints).number == 30

    # Restore the correction, finish, and verify both recovered clients converge.
    repo.restore_split_event(mile_two.id)
    repo.create_split_event(SplitEvent(race_session_id=shared.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=90, elapsed_seconds=320, event_order=3))
    synchronize_shared_timing(client_a)
    synchronize_shared_timing(client_b)
    assert athlete_finished(client_a.splits, client_a.meet_config.checkpoints)
    assert athlete_finished(client_b.splits, client_b.meet_config.checkpoints)
    assert next_checkpoint(client_a.splits, client_a.meet_config.checkpoints) is None

    recovered = SessionState(**vars(client_b).copy())
    recovered.active_race_session_id = None
    recovered.splits = []
    restore_timing_state(recovered)
    assert athlete_finished(recovered.splits, recovered.meet_config.checkpoints)
    assert [split.checkpoint_number for split in recovered.splits] == [10, 30, 90]


def test_four_clients_converge_and_starter_recovers_after_failed_poll():
    from split_tracker.calculations import next_checkpoint
    from split_tracker.models import Checkpoint
    from split_tracker.repository import RepositoryError

    repo, race, starter = make_repo_and_session()
    checkpoints = [
        Checkpoint(number=1, label="Mile 1", distance_meters=1609.344),
        Checkpoint(number=2, label="Mile 2", distance_meters=3218.688),
        Checkpoint(number=3, label="Mile 3", distance_meters=4828.032),
        Checkpoint(number=4, label="Finish", distance_meters=5000, is_finish=True),
    ]
    starter.meet_config.checkpoints = checkpoints
    starter.meet_config.race_distance_meters = 5000
    ready = repo.create_race_session(RaceSession(race_id=race.id, status="ready"))
    repo.create_race_session_checkpoints(ready.id, checkpoints)
    starter.active_race_session_id = ready.id
    clients = [starter]
    for name in ("Mile 1", "Mile 2", "Mile 3"):
        client = SessionState(**vars(starter).copy())
        client.timer_name = name
        client.splits = []
        clients.append(client)

    persisted_start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    start_and_synchronize_shared_timing(starter, now_utc=persisted_start)
    assert starter.active_race_session_id == ready.id
    assert starter.initiated_start_session_id == ready.id
    assert starter.timing_restored_for_race_id == race.id

    for order, client in enumerate(clients[1:], start=1):
        repo.create_split_event(
            SplitEvent(
                race_session_id=ready.id,
                athlete_id="a1",
                athlete_name="Alex",
                checkpoint_number=order,
                checkpoint_label=f"Mile {order}",
                elapsed_seconds=order * 300,
                event_order=order,
                recorded_by=client.timer_name,
            )
        )

    class FailsOnce:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.failed = False

        def get_race_session(self, session_id):
            if not self.failed:
                self.failed = True
                raise RepositoryError("one failed poll")
            return self.wrapped.get_race_session(session_id)

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    starter.repository = FailsOnce(repo)
    assert poll_shared_timing(starter) is None
    assert starter.active_race_session_id == ready.id
    assert starter.sync_error == "one failed poll"

    assert poll_shared_timing(starter) is not None
    assert starter.sync_error == ""
    assert starter.loaded_split_event_count == 3
    assert starter.latest_event_id == repo.list_active_split_events(ready.id)[-1].id
    assert [split.checkpoint_number for split in starter.splits] == [1, 2, 3]
    assert next_checkpoint(starter.splits, starter.meet_config.checkpoints).label == "Finish"
    assert repo.get_race_session(ready.id).started_at == persisted_start

    # Every other client performs fresh reads and converges with the starter.
    for client in clients[1:]:
        assert poll_shared_timing(client) is not None
        assert [split.split_id for split in client.splits] == [split.split_id for split in starter.splits]
        assert client.loaded_split_event_count == 3

    before_ids = [split.split_id for split in starter.splits]
    before_count = starter.poll_cycle_count
    poll_shared_timing(starter)
    assert [split.split_id for split in starter.splits] == before_ids
    assert starter.poll_cycle_count == before_count + 1


def test_direct_start_and_detected_start_use_equivalent_authoritative_state():
    repo, race, starter = make_repo_and_session()
    ready = repo.create_race_session(RaceSession(race_id=race.id, status="ready"))
    repo.create_race_session_checkpoints(ready.id, starter.meet_config.checkpoints)
    starter.active_race_session_id = ready.id
    waiting = SessionState(**vars(starter).copy())
    waiting.splits = []
    started_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    observed_at = datetime(2026, 1, 1, 12, 0, 12, tzinfo=timezone.utc)

    direct = start_and_synchronize_shared_timing(
        starter,
        now_perf=112.0,
        now_utc=started_at,
    )
    detected = poll_shared_timing(
        waiting,
        now_perf=124.0,
        now_utc=observed_at,
    )

    assert direct.id == detected.id == ready.id
    assert direct.started_at == detected.started_at == started_at
    assert starter.active_race_session_id == waiting.active_race_session_id
    assert starter.timing_restored_for_race_id == waiting.timing_restored_for_race_id == race.id
    assert starter.race_clock.status == waiting.race_clock.status == "running"
    assert starter.race_clock.start_perf_counter == 112.0
    assert waiting.race_clock.start_perf_counter == 112.0
    assert starter.splits == waiting.splits == []
    assert starter.persisted_race_status == waiting.persisted_race_status == "running"
    assert starter.loaded_split_event_count == waiting.loaded_split_event_count == 0
    assert starter.initiated_start_session_id == ready.id
    assert waiting.get("initiated_start_session_id", "") == ""
