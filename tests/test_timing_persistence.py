"""Tests for persistent live timing sessions and split events."""

from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from split_tracker.calculations import generate_checkpoints
from split_tracker.models import Athlete, MeetConfig, RaceClock
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, RepositoryError, SplitEvent, SupabaseRaceRepository, _race_session_to_row, _split_event_to_row
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
    record_authoritative_split,
    rebuild_splits_from_events,
    refresh_splits_from_repository,
    restore_timing_state,
    start_and_synchronize_shared_timing,
    synchronize_shared_timing,
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
    repo.replace_race_athletes(race.id, [Athlete(name="Alex", bib_number="7", athlete_id="a1")])
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


def test_pause_resume_and_completion_elapsed_persistence(monkeypatch):
    repo, race, session = make_repo_and_session()
    started = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)))
    session.active_race_session_id = started.id
    server_times = iter([
        datetime(2026, 1, 1, 12, 1, 15, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 12, 3, 5, tzinfo=timezone.utc),
    ])
    monkeypatch.setattr("split_tracker.repository.utc_now", lambda: next(server_times))

    paused = persist_pause(session, now_utc=datetime(2036, 1, 1, tzinfo=timezone.utc))
    resumed = persist_resume(session, now_utc=datetime(2036, 1, 1, tzinfo=timezone.utc))
    elapsed_after_resume = persisted_elapsed_seconds(resumed, datetime(2026, 1, 1, 12, 2, 10, tzinfo=timezone.utc))
    completed = persist_completion(session, now_utc=datetime(2036, 1, 1, tzinfo=timezone.utc))

    assert paused.status == "paused"
    assert paused.elapsed_offset_seconds == 75
    assert resumed.status == "running"
    assert elapsed_after_resume == 85
    assert completed.status == "completed"
    assert completed.elapsed_offset_seconds == 140
    assert completed.ended_at is not None


def test_rejected_stale_pause_reloads_completed_shared_state(monkeypatch):
    repo, race, client = make_repo_and_session()
    started_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=started_at))
    repo.create_race_session_checkpoints(shared.id, client.meet_config.checkpoints)
    client.active_race_session_id = shared.id
    synchronize_shared_timing(client, now_utc=started_at)
    monkeypatch.setattr("split_tracker.repository.utc_now", lambda: started_at + timedelta(minutes=1))
    repo.transition_race_session(shared.id, "complete")

    with pytest.raises(RepositoryError, match="shared race is completed"):
        persist_pause(client, now_utc=datetime(2036, 1, 1, tzinfo=timezone.utc))

    assert client.persisted_race_status == "completed"
    assert client.race_clock.status == "ended"
    assert client.projected_race_state.race_session.status == "completed"


def test_refresh_reconstructs_each_authoritative_lifecycle_state(monkeypatch):
    repo, race, controller = make_repo_and_session()
    started_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=started_at))
    repo.create_race_session_checkpoints(shared.id, controller.meet_config.checkpoints)
    controller.active_race_session_id = shared.id
    times = iter([
        started_at + timedelta(seconds=30),
        started_at + timedelta(seconds=60),
        started_at + timedelta(seconds=90),
    ])
    monkeypatch.setattr("split_tracker.repository.utc_now", lambda: next(times))

    persist_pause(controller)
    paused_browser = SessionState(**vars(controller).copy())
    paused_browser.active_race_session_id = None
    assert restore_timing_state(paused_browser).status == "paused"
    assert paused_browser.race_clock.status == "paused"

    persist_resume(controller)
    running_browser = SessionState(**vars(controller).copy())
    running_browser.active_race_session_id = None
    assert restore_timing_state(running_browser).status == "running"
    assert running_browser.race_clock.status == "running"

    persist_completion(controller)
    completed_browser = SessionState(**vars(controller).copy())
    completed_browser.active_race_session_id = None
    assert restore_timing_state(completed_browser).status == "completed"
    assert completed_browser.race_clock.status == "ended"


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

    # Database event_order is authoritative even when insertion timestamps differ.
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

    started = persist_start(client_a, now_perf=100.0, now_utc=original_start)
    observed = synchronize_shared_timing(
        client_b,
        now_perf=230.0,
        now_utc=datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc),
    )

    assert observed.id == ready.id
    assert observed.started_at == started.started_at
    assert client_b.active_race_session_id == ready.id
    assert client_b.race_clock.status == "running"
    expected_elapsed = (datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc) - started.started_at).total_seconds()
    assert client_b.race_clock.start_perf_counter == 230.0 - max(0.0, expected_elapsed)
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
    assert started_by_first.started_at == observed_by_second.started_at
    assert repo.get_race_session(ready.id).started_at == started_by_first.started_at


def test_independent_clients_without_session_id_converge_on_atomic_start():
    repo, race, first = make_repo_and_session()
    second = SessionState(**vars(first).copy())
    first_start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    later_attempt = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)

    started_by_first = persist_start(first, now_utc=first_start)
    observed_by_second = persist_start(second, now_utc=later_attempt)

    sessions = repo.list_race_sessions_for_race(race.id)
    assert started_by_first.id == observed_by_second.id
    assert first.active_race_session_id == second.active_race_session_id == sessions[0].id
    assert started_by_first.started_at == observed_by_second.started_at
    assert len(sessions) == 1
    assert len(repo.list_race_session_checkpoints(sessions[0].id)) == len(first.meet_config.checkpoints)


def test_repository_serializes_simultaneous_session_creation():
    repo, race, state = make_repo_and_session()

    def start():
        return repo.get_or_create_active_race_session(race.id, state.meet_config.checkpoints)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: start(), range(2)))

    sessions = repo.list_race_sessions_for_race(race.id)
    snapshots = repo.list_race_session_checkpoints(first.id)
    assert first.id == second.id
    assert first.started_at == second.started_at
    assert len([item for item in sessions if item.status in {"ready", "running", "paused"}]) == 1
    assert len(snapshots) == len(state.meet_config.checkpoints)


def test_terminal_sessions_allow_a_later_new_active_session():
    for terminal_status in ("completed", "cancelled"):
        repo, race, state = make_repo_and_session()
        historical = repo.create_race_session(
            RaceSession(
                race_id=race.id,
                status=terminal_status,
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )

        active = persist_start(state, now_utc=datetime(2026, 1, 2, tzinfo=timezone.utc))

        assert active.id != historical.id
        assert [item.status for item in repo.list_race_sessions_for_race(race.id)] == [terminal_status, "running"]


def test_refresh_restores_session_created_by_another_client():
    _, _, starter = make_repo_and_session()
    waiting = SessionState(**vars(starter).copy())
    started = persist_start(starter, now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc))

    restored = restore_timing_state(
        waiting, now_utc=datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
    )

    assert restored.id == started.id
    assert waiting.active_race_session_id == started.id
    assert waiting.race_clock.status == "running"


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

    repo.create_split_event(SplitEvent(race_session_id=shared.id, athlete_id="a1", athlete_name="Alex", checkpoint_number=10, elapsed_seconds=100, event_order=1))
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
    started = start_and_synchronize_shared_timing(starter, now_utc=persisted_start)
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
    assert repo.get_race_session(ready.id).started_at == started.started_at

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

    direct = start_and_synchronize_shared_timing(
        starter,
        now_perf=112.0,
        now_utc=started_at,
    )
    detected = poll_shared_timing(
        waiting,
        now_perf=124.0,
        now_utc=direct.started_at + timedelta(seconds=12),
    )

    assert direct.id == detected.id == ready.id
    assert direct.started_at == detected.started_at
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


def test_authoritative_button_action_inserts_then_reloads_without_local_speculation(monkeypatch):
    from split_tracker.calculations import next_checkpoint

    repo, race, client = make_repo_and_session()
    started_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=started_at))
    repo.create_race_session_checkpoints(shared.id, client.meet_config.checkpoints)
    client.active_race_session_id = shared.id
    client.timer_name = "Mile one"
    server_at = datetime(2026, 1, 1, 12, 1, 10, tzinfo=timezone.utc)
    monkeypatch.setattr("split_tracker.repository.utc_now", lambda: server_at)

    result = record_authoritative_split(
        client, "a1", now_utc=datetime(2036, 1, 1, tzinfo=timezone.utc)
    )

    assert result.status == "inserted"
    assert result.event.elapsed_seconds == 70
    assert result.event.recorded_at == server_at
    assert result.event.recorded_by == "Mile one"
    assert [split.split_id for split in client.splits] == [result.event.id]
    assert next_checkpoint(client.splits, client.meet_config.checkpoints).number == 2
    assert client.last_split_action["result"] == "inserted"
    assert client.last_split_action["events_after_reload"] == 1


def test_starter_and_nonstarter_can_both_record_authoritative_splits():
    repo, race, starter = make_repo_and_session()
    ready = repo.create_race_session(RaceSession(race_id=race.id, status="ready"))
    repo.create_race_session_checkpoints(ready.id, starter.meet_config.checkpoints)
    starter.active_race_session_id = ready.id
    other = SessionState(**vars(starter).copy())
    other.splits = []
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    started = start_and_synchronize_shared_timing(starter, now_utc=start)
    start = started.started_at
    poll_shared_timing(other, now_utc=start)

    first = record_authoritative_split(starter, "a1", now_utc=start + timedelta(minutes=1))
    poll_shared_timing(other, now_utc=start + timedelta(minutes=1))
    second = record_authoritative_split(other, "a1", now_utc=start + timedelta(minutes=2))
    poll_shared_timing(starter, now_utc=start + timedelta(minutes=2))

    assert first.event.checkpoint_number == 1
    assert second.event.checkpoint_number == 2
    assert [split.split_id for split in starter.splits] == [first.event.id, second.event.id]
    assert [split.split_id for split in other.splits] == [first.event.id, second.event.id]


def test_concurrent_duplicate_loser_reloads_instead_of_advancing_twice():
    repo, race, client = make_repo_and_session()
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=start))
    repo.create_race_session_checkpoints(shared.id, client.meet_config.checkpoints)
    client.active_race_session_id = shared.id

    class ConcurrentWinner:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.inserted = False

        def record_shared_split(self, race_session_id, athlete_id, checkpoint_number, recorded_by, request_id):
            if not self.inserted:
                self.inserted = True
                self.wrapped.record_shared_split(
                    race_session_id, athlete_id, checkpoint_number, "winner", "winner"
                )
            return self.wrapped.record_shared_split(
                race_session_id, athlete_id, checkpoint_number, recorded_by, request_id
            )

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    client.repository = ConcurrentWinner(repo)
    result = record_authoritative_split(client, "a1", now_utc=datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc))

    assert result.status == "duplicate"
    assert [event.id for event in repo.list_active_split_events(shared.id)] == ["winner"]
    assert [split.split_id for split in client.splits] == ["winner"]
    assert client.last_split_action["events_after_reload"] == 1


def test_failed_authoritative_insert_does_not_advance_progress():
    import pytest
    from split_tracker.repository import RepositoryError

    repo, race, client = make_repo_and_session()
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=datetime.now(timezone.utc)))
    repo.create_race_session_checkpoints(shared.id, client.meet_config.checkpoints)
    client.active_race_session_id = shared.id

    class FailedInsert:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def record_shared_split(self, *_args):
            raise RepositoryError("database unavailable")

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    client.repository = FailedInsert(repo)
    with pytest.raises(RepositoryError, match="database unavailable"):
        record_authoritative_split(client, "a1")

    assert client.splits == []
    assert client.split_sequence == 0
    assert client.last_split_action["result"] == "error"


def test_fast_path_uses_one_write_and_preserves_three_click_times():
    from split_tracker.timing_persistence import synchronize_shared_timing

    repo, race, client = make_repo_and_session()
    athletes = [Athlete(name=name, athlete_id=athlete_id, display_order=index)
                for index, (name, athlete_id) in enumerate((("Alex", "a1"), ("Blair", "a2"), ("Casey", "a3")))]
    repo.replace_race_athletes(race.id, athletes)
    client.athletes = athletes
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    shared = repo.create_race_session(RaceSession(race_id=race.id, status="running", started_at=start))
    repo.create_race_session_checkpoints(shared.id, client.meet_config.checkpoints)
    client.active_race_session_id = shared.id
    synchronize_shared_timing(client, now_utc=start)

    class CountingRepository:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.calls = []

        def __getattr__(self, name):
            operation = getattr(self.wrapped, name)
            if not callable(operation):
                return operation

            def counted(*args, **kwargs):
                self.calls.append(name)
                return operation(*args, **kwargs)
            return counted

    counting = CountingRepository(repo)
    client.repository = counting
    clicks = [
        datetime(2026, 1, 1, 12, 1, 0, 100000, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 12, 1, 0, 200000, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 12, 1, 0, 300000, tzinfo=timezone.utc),
    ]
    results = [record_authoritative_split(client, athlete_id, now_utc=clicked)
               for athlete_id, clicked in zip(("a1", "a2", "a3"), clicks)]

    assert counting.calls == ["record_shared_split"] * 3
    assert [result.event.event_order for result in results] == [1, 2, 3]
    assert [result.event.recorded_at for result in results] != clicks
    assert len({result.event.id for result in results}) == 3
    assert len(client.projected_race_state.events) == 3
    assert client.last_split_action["timings_ms"]["post_insert_synchronization"] == 0.0


def test_clock_skew_cannot_change_server_timing_or_progression(monkeypatch):
    repo, race, client = make_repo_and_session()
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    shared = repo.create_race_session(
        RaceSession(race_id=race.id, status="running", started_at=start)
    )
    repo.create_race_session_checkpoints(shared.id, client.meet_config.checkpoints)
    client.active_race_session_id = shared.id
    server_times = iter([
        start + timedelta(seconds=60), start + timedelta(seconds=60),
        start + timedelta(seconds=120), start + timedelta(seconds=120),
    ])
    monkeypatch.setattr("split_tracker.repository.utc_now", lambda: next(server_times))

    first = record_authoritative_split(
        client, "a1", now_utc=datetime(2040, 1, 1, tzinfo=timezone.utc)
    )
    second = record_authoritative_split(
        client, "a1", now_utc=datetime(2000, 1, 1, tzinfo=timezone.utc)
    )

    assert [first.event.elapsed_seconds, second.event.elapsed_seconds] == [60, 120]
    assert [first.event.event_order, second.event.event_order] == [1, 2]
    assert [event.id for event in client.projected_race_state.events] == [
        first.event.id, second.event.id
    ]
    assert client.projected_race_state.athletes[0].finished


def test_server_elapsed_time_includes_offset_after_resume(monkeypatch):
    repo, race, client = make_repo_and_session()
    resumed_at = datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc)
    shared = repo.create_race_session(RaceSession(
        race_id=race.id,
        status="running",
        started_at=resumed_at,
        elapsed_offset_seconds=45.0,
    ))
    repo.create_race_session_checkpoints(shared.id, client.meet_config.checkpoints)
    client.active_race_session_id = shared.id
    server_at = resumed_at + timedelta(seconds=15)
    monkeypatch.setattr("split_tracker.repository.utc_now", lambda: server_at)

    result = record_authoritative_split(client, "a1")

    assert result.event.elapsed_seconds == 60.0


def test_retry_with_same_request_id_returns_original_event(monkeypatch):
    repo, race, client = make_repo_and_session()
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    shared = repo.create_race_session(
        RaceSession(race_id=race.id, status="running", started_at=start)
    )
    repo.create_race_session_checkpoints(shared.id, client.meet_config.checkpoints)
    server_at = start + timedelta(seconds=30)
    monkeypatch.setattr("split_tracker.repository.utc_now", lambda: server_at)

    first = repo.record_shared_split(shared.id, "a1", 1, "Coach", "request-1")
    retried = repo.record_shared_split(shared.id, "a1", 1, "Coach", "request-1")

    assert retried == first
    assert len(repo.list_active_split_events(shared.id)) == 1
    assert first.checkpoint_number == 1


def test_lost_response_retry_reuses_request_without_advancing_twice(monkeypatch):
    import pytest
    from split_tracker.repository import RepositoryError

    repo, race, client = make_repo_and_session()
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    shared = repo.create_race_session(
        RaceSession(race_id=race.id, status="running", started_at=start)
    )
    repo.create_race_session_checkpoints(shared.id, client.meet_config.checkpoints)
    client.active_race_session_id = shared.id
    server_at = start + timedelta(seconds=30)
    monkeypatch.setattr("split_tracker.repository.utc_now", lambda: server_at)

    class LostFirstResponse:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.request_ids = []

        def record_shared_split(self, *args):
            self.request_ids.append(args[-1])
            event = self.wrapped.record_shared_split(*args)
            if len(self.request_ids) == 1:
                raise RepositoryError("connection lost after commit")
            return event

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

    unreliable = LostFirstResponse(repo)
    client.repository = unreliable
    with pytest.raises(RepositoryError, match="connection lost after commit"):
        record_authoritative_split(client, "a1")
    assert client.splits == []

    retried = record_authoritative_split(client, "a1")

    assert unreliable.request_ids[0] == unreliable.request_ids[1]
    assert retried.event.checkpoint_number == 1
    assert len(repo.list_active_split_events(shared.id)) == 1
    assert client.projected_race_state.athletes[0].next_checkpoint.number == 2


def test_supabase_split_rpc_payload_omits_authoritative_timing_fields():
    class Result:
        data = [{
            "id": "request-1",
            "race_session_id": "session-1",
            "athlete_id": "athlete-1",
            "checkpoint_number": 1,
            "checkpoint_label": "Mile 1",
            "elapsed_seconds": 60,
            "event_order": 1,
            "recorded_at": "2026-01-01T12:01:00+00:00",
        }]

    class Operation:
        def execute(self):
            return Result()

    class Client:
        def __init__(self):
            self.calls = []

        def rpc(self, name, params):
            self.calls.append((name, params))
            return Operation()

    client = Client()
    event = SupabaseRaceRepository(client).record_shared_split(
        "session-1", "athlete-1", 1, "Coach", "request-1"
    )

    name, params = client.calls[0]
    assert name == "record_shared_split"
    assert set(params["p_event"]) == {
        "id", "race_session_id", "athlete_id", "checkpoint_number", "recorded_by"
    }
    assert "elapsed_seconds" not in params["p_event"]
    assert "recorded_at" not in params["p_event"]
    assert event.elapsed_seconds == 60


def test_supabase_lifecycle_rpc_sends_only_session_and_action():
    class Result:
        data = [{"id": "session-1", "race_id": "race-1", "status": "paused", "started_at": "2026-01-01T12:00:00+00:00", "paused_at": "2026-01-01T12:01:00+00:00", "elapsed_offset_seconds": 60}]

    class Operation:
        def execute(self): return Result()

    class Client:
        def __init__(self): self.calls = []
        def rpc(self, name, params):
            self.calls.append((name, params))
            return Operation()

    client = Client()
    session = SupabaseRaceRepository(client).transition_race_session("session-1", "pause")

    assert client.calls == [("transition_race_session", {"p_session_id": "session-1", "p_action": "pause"})]
    assert session.status == "paused"
    assert session.elapsed_offset_seconds == 60
