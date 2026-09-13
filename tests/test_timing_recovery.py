"""Live timing correction, replay, activity, and race-isolation tests."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest

from split_tracker.models import Athlete, Checkpoint, MeetConfig, RaceClock
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, RepositoryError, SplitEvent
from split_tracker.timing_persistence import persist_event_correction, persist_manual_correction, synchronize_shared_timing
from split_tracker.timing_recovery import latest_active_event, recent_timing_activity


class State(SimpleNamespace):
    def get(self, key, default=None):
        return getattr(self, key, default)

    def setdefault(self, key, default):
        if not hasattr(self, key): setattr(self, key, default)
        return getattr(self, key)


def correction_setup(*, race_name="Race", athlete_name="Jordan Lee"):
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Invite"))
    race = repo.create_race(Race(meet_id=meet.id, name=race_name, distance_meters=3200))
    athlete = Athlete(name=athlete_name, athlete_id=str(uuid4()))
    other = Athlete(name="Other Runner", athlete_id=str(uuid4()))
    repo.replace_race_athletes(race.id, [athlete, other])
    checkpoints = [Checkpoint(1, "Mile 1", 1609.344), Checkpoint(2, "Finish", 3200, True)]
    session = repo.create_race_session(RaceSession(race_id=race.id, status="paused", started_at=datetime.now(timezone.utc), elapsed_offset_seconds=1000))
    repo.create_race_session_checkpoints(session.id, checkpoints)
    state = State(
        repository=repo, selected_race_id=race.id, active_race_session_id=session.id,
        meet_config=MeetConfig(meet_name=meet.name, race_name=race.name, race_distance_meters=3200, checkpoints=checkpoints),
        athletes=[athlete, other], splits=[], split_sequence=0, race_clock=RaceClock(),
        timer_name="Coach A", pending_manual_split_request_ids={},
    )
    synchronize_shared_timing(state)
    return repo, race, session, athlete, other, state


def add_event(repo, session, athlete, checkpoint, elapsed, order):
    return repo.create_split_event(SplitEvent(
        race_session_id=session.id, athlete_id=athlete.athlete_id,
        athlete_name=athlete.name, checkpoint_number=checkpoint,
        checkpoint_label="Mile 1" if checkpoint == 1 else "Finish",
        elapsed_seconds=elapsed, event_order=order,
    ))


def test_undo_latest_split_replays_only_current_session_and_other_athlete_is_unchanged():
    repo, _, session, athlete, other, state = correction_setup()
    first = add_event(repo, session, athlete, 1, 300, 1)
    latest = add_event(repo, session, other, 1, 310, 2)
    synchronize_shared_timing(state)

    target = latest_active_event(state.persisted_split_events, session.id)
    persist_event_correction(state, target)

    assert target.id == latest.id
    assert repo.list_active_split_events(session.id) == [first]
    projected = {item.athlete.athlete_id: item for item in state.projected_race_state.athletes}
    assert projected[athlete.athlete_id].next_checkpoint.number == 2
    assert projected[other.athlete_id].next_checkpoint.number == 1


def test_race_and_session_mismatch_and_double_correction_fail_safely():
    repo, race, session, athlete, _, state = correction_setup(athlete_name="Same Name")
    event = add_event(repo, session, athlete, 1, 300, 1)
    other_race = repo.create_race(Race(meet_id=race.meet_id, name="Other", distance_meters=3200))
    other_session = repo.create_race_session(RaceSession(race_id=other_race.id, status="paused", elapsed_offset_seconds=1000))

    with pytest.raises(RepositoryError, match="no longer matches"):
        repo.invalidate_split_event(event.id, other_session.id, athlete.athlete_id, 1, "Coach")
    repo.invalidate_split_event(event.id, session.id, athlete.athlete_id, 1, "Coach")
    with pytest.raises(RepositoryError, match="already corrected"):
        repo.invalidate_split_event(event.id, session.id, athlete.athlete_id, 1, "Coach B")
    assert repo.list_all_split_events(other_session.id) == []


def test_correction_uses_event_session_instead_of_stale_active_session_state():
    repo, _, session, athlete, _, state = correction_setup()
    event = add_event(repo, session, athlete, 1, 300, 1)
    state.active_race_session_id = "stale-browser-session"

    corrected = persist_event_correction(state, event)

    assert corrected.race_session_id == event.race_session_id
    assert corrected.target_event_id == event.id


def test_identical_athlete_names_in_simultaneous_races_are_isolated_by_ids():
    repo, race_a, session_a, athlete_a, _, _ = correction_setup(athlete_name="Jordan Lee")
    race_b = repo.create_race(Race(meet_id=race_a.meet_id, name="Race B", distance_meters=3200))
    athlete_b = Athlete(name="Jordan Lee", athlete_id=str(uuid4()))
    repo.replace_race_athletes(race_b.id, [athlete_b])
    session_b = repo.create_race_session(RaceSession(race_id=race_b.id, status="paused", elapsed_offset_seconds=1000))
    event_a = add_event(repo, session_a, athlete_a, 1, 300, 1)
    event_b = add_event(repo, session_b, athlete_b, 1, 301, 1)

    repo.invalidate_split_event(event_a.id, session_a.id, athlete_a.athlete_id, 1, "Coach A")

    assert repo.list_active_split_events(session_a.id) == []
    assert repo.list_active_split_events(session_b.id) == [event_b]


def test_concurrent_correction_allows_exactly_one_winner():
    repo, _, session, athlete, _, _ = correction_setup()
    event = add_event(repo, session, athlete, 1, 300, 1)

    def correct(actor):
        try:
            repo.invalidate_split_event(event.id, session.id, athlete.athlete_id, 1, actor)
            return "corrected"
        except RepositoryError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(correct, ["Coach A", "Coach B"]))

    assert sorted(outcomes) == ["corrected", "stale"]


def test_stale_undo_refuses_when_another_coach_recorded_a_newer_split():
    repo, _, session, athlete, other, _ = correction_setup()
    stale_target = add_event(repo, session, athlete, 1, 300, 1)
    add_event(repo, session, other, 1, 305, 2)

    with pytest.raises(RepositoryError, match="newer split"):
        repo.invalidate_split_event(
            stale_target.id, session.id, athlete.athlete_id, 1, "Coach A",
            require_latest=True,
        )

    assert stale_target.id in {event.id for event in repo.list_active_split_events(session.id)}


def test_specific_older_correction_preserves_later_event_and_accepts_manual_replacement():
    repo, _, session, athlete, _, state = correction_setup()
    mile = add_event(repo, session, athlete, 1, 300, 1)
    finish = add_event(repo, session, athlete, 2, 700, 2)
    synchronize_shared_timing(state)

    persist_event_correction(state, mile)
    athlete_state = next(item for item in state.projected_race_state.athletes if item.athlete.athlete_id == athlete.athlete_id)
    assert athlete_state.completed_split_count == 1
    assert finish.id in {event.id for event in state.projected_race_state.events}
    assert athlete_state.splits[0].checkpoint_number == 2

    manual = persist_manual_correction(state, athlete.athlete_id, 1, 290)
    athlete_state = next(item for item in state.projected_race_state.athletes if item.athlete.athlete_id == athlete.athlete_id)
    assert manual.correction_type == "manual"
    assert athlete_state.completed_split_count == 2
    assert athlete_state.finished is True


def test_valid_missed_split_advances_progress_and_invalid_sequence_is_rejected():
    repo, _, session, athlete, _, state = correction_setup()

    with pytest.raises(RepositoryError, match="next missing"):
        repo.record_manual_split(session.id, athlete.athlete_id, 2, 600, "Coach", str(uuid4()))
    persist_manual_correction(state, athlete.athlete_id, 1, 300)

    athlete_state = next(item for item in state.projected_race_state.athletes if item.athlete.athlete_id == athlete.athlete_id)
    assert athlete_state.completed_split_count == 1
    assert athlete_state.next_checkpoint.number == 2


def test_recent_activity_is_deterministic_scoped_and_marks_corrections():
    repo, _, session, athlete, _, state = correction_setup()
    event = add_event(repo, session, athlete, 1, 300, 1)
    repo.invalidate_split_event(event.id, session.id, athlete.athlete_id, 1, "Coach A")
    manual = repo.record_manual_split(session.id, athlete.athlete_id, 1, 290, "Coach A", str(uuid4()))
    other = RaceSession(race_id="other", id="other-session", status="paused")
    unrelated = SplitEvent(race_session_id=other.id, athlete_id=athlete.athlete_id, checkpoint_number=1, elapsed_seconds=1, event_order=99)

    activity = recent_timing_activity([*repo.list_all_split_events(session.id), unrelated], session.id)

    assert [item.event_id for item in activity] == [manual.id, event.id]
    assert activity[0].label.startswith("Manual")
    assert activity[1].label.startswith("Correction")
    assert all(item.event_id != unrelated.id for item in activity)


def test_wrong_athlete_reassignment_is_append_only_and_updates_projection():
    repo, race, session, emma, sarah, state = correction_setup(athlete_name="Emma")
    wrong = add_event(repo, session, emma, 1, 300, 1)

    history = repo.correct_split_athlete(wrong.id, session.id, emma.athlete_id, 1, sarah.athlete_id, "Coach A", str(uuid4()))
    synchronize_shared_timing(state)

    projected = {item.athlete.athlete_id: item for item in state.projected_race_state.athletes}
    assert [item.event_type for item in history] == ["split_voided", "split_corrected"]
    assert repo.split_events[wrong.id] == wrong
    assert projected[emma.athlete_id].completed_split_count == 0
    assert projected[sarah.athlete_id].completed_split_count == 1
    assert projected[sarah.athlete_id].latest_elapsed_seconds == 300


def test_reassignment_rejects_duplicate_checkpoint_and_second_correction():
    repo, _, session, emma, sarah, _ = correction_setup(athlete_name="Emma")
    wrong = add_event(repo, session, emma, 1, 300, 1)
    add_event(repo, session, sarah, 1, 310, 2)
    with pytest.raises(RepositoryError, match="already has"):
        repo.correct_split_athlete(wrong.id, session.id, emma.athlete_id, 1, sarah.athlete_id, "Coach", str(uuid4()))
    repo.invalidate_split_event(wrong.id, session.id, emma.athlete_id, 1, "Coach")
    with pytest.raises(RepositoryError, match="already changed"):
        repo.correct_split_athlete(wrong.id, session.id, emma.athlete_id, 1, sarah.athlete_id, "Coach", str(uuid4()))


def test_undo_finish_appends_audit_event_and_returns_athlete_to_finish_checkpoint():
    repo, _, session, athlete, _, state = correction_setup()
    first = add_event(repo, session, athlete, 1, 300, 1)
    finish = add_event(repo, session, athlete, 2, 700, 2)
    synchronize_shared_timing(state)
    assert next(item for item in state.projected_race_state.athletes if item.athlete.athlete_id == athlete.athlete_id).finished

    repo.invalidate_split_event(finish.id, session.id, athlete.athlete_id, 2, "Coach", require_latest=True)
    synchronize_shared_timing(state)

    projected = next(item for item in state.projected_race_state.athletes if item.athlete.athlete_id == athlete.athlete_id)
    assert not projected.finished and projected.next_checkpoint.number == 2
    assert [event.id for event in state.projected_race_state.events] == [first.id]
    assert len(repo.list_all_split_events(session.id)) == 3
