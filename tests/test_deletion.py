"""Tests for predictable deletion and cascade behavior."""

from __future__ import annotations

from split_tracker.models import Athlete, RaceClock
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, SplitEvent, TemplateRace
from split_tracker.state import (
    cleanup_after_meet_delete,
    cleanup_after_race_delete,
    cleanup_after_roster_clear,
    cleanup_after_session_delete,
    initialize_state,
)


class Session(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


def build_delete_fixture():
    repo = InMemoryRaceRepository()
    meet_one = repo.create_meet(Meet(name="Meet One", status="active"))
    meet_two = repo.create_meet(Meet(name="Meet Two", status="active"))
    race_one = repo.create_race(Race(meet_id=meet_one.id, name="Boys", distance_meters=800.0, status="completed"))
    race_two = repo.create_race(Race(meet_id=meet_one.id, name="Girls", distance_meters=800.0, status="completed", display_order=1))
    other_race = repo.create_race(Race(meet_id=meet_two.id, name="Open", distance_meters=800.0, status="completed"))
    for race, athlete_id in [(race_one, "a1"), (race_two, "a2"), (other_race, "a3")]:
        repo.replace_race_athletes(race.id, [Athlete(name=f"Runner {athlete_id}", athlete_id=athlete_id)])
        first = repo.create_race_session(RaceSession(race_id=race.id, status="completed"))
        second = repo.create_race_session(RaceSession(race_id=race.id, status="completed"))
        repo.create_split_event(SplitEvent(race_session_id=first.id, athlete_id=athlete_id, checkpoint_number=1, elapsed_seconds=60.0, event_order=1))
        repo.create_split_event(SplitEvent(race_session_id=second.id, athlete_id=athlete_id, checkpoint_number=1, elapsed_seconds=65.0, event_order=1))
    return repo, meet_one, meet_two, race_one, race_two, other_race


def test_deleting_one_session_removes_only_its_split_events():
    repo, _, _, race_one, race_two, _ = build_delete_fixture()
    session_to_delete = repo.list_race_sessions_for_race(race_one.id)[0]
    sibling_session = repo.list_race_sessions_for_race(race_one.id)[1]

    assert repo.delete_race_session(session_to_delete.id) is True

    assert repo.get_race_session(session_to_delete.id) is None
    assert repo.list_all_split_events(session_to_delete.id) == []
    assert len(repo.list_active_split_events(sibling_session.id)) == 1
    assert len(repo.list_race_sessions_for_race(race_two.id)) == 2


def test_deleting_one_race_removes_owned_roster_sessions_and_splits_only():
    repo, meet_one, _, race_one, race_two, _ = build_delete_fixture()
    session_ids = [session.id for session in repo.list_race_sessions_for_race(race_one.id)]

    assert repo.delete_race(race_one.id) is True

    assert repo.get_race(race_one.id) is None
    assert not any(key[0] == race_one.id for key in repo.race_athletes)
    assert all(repo.get_race_session(session_id) is None for session_id in session_ids)
    assert repo.get_meet(meet_one.id) is not None
    assert repo.get_race(race_two.id) is not None
    assert len(repo.list_race_athletes(race_two.id, include_inactive=True)) == 1


def test_deleting_one_meet_removes_owned_data_and_leaves_other_meets():
    repo, meet_one, meet_two, race_one, race_two, other_race = build_delete_fixture()

    assert repo.delete_meet(meet_one.id) is True

    assert repo.get_meet(meet_one.id) is None
    assert repo.get_race(race_one.id) is None
    assert repo.get_race(race_two.id) is None
    assert repo.get_meet(meet_two.id) is not None
    assert repo.get_race(other_race.id) is not None
    assert len(repo.list_race_athletes(other_race.id, include_inactive=True)) == 1
    assert len(repo.list_race_sessions_for_race(other_race.id)) == 2


def test_clear_one_roster_leaves_other_rosters_and_sessions():
    repo, _, _, race_one, race_two, _ = build_delete_fixture()

    assert repo.clear_race_roster(race_one.id) is True

    assert not any(key[0] == race_one.id for key in repo.race_athletes)
    assert len(repo.list_race_athletes(race_two.id, include_inactive=True)) == 1
    assert len(repo.list_race_sessions_for_race(race_one.id)) == 2


def test_full_test_data_cleanup_preserves_templates():
    repo, *_ = build_delete_fixture()
    template = repo.seed_default_xc_template()
    repo.create_template(template.__class__(name="Custom"), [TemplateRace(template_id="ignored", name="Race", distance_meters=1000.0)])

    assert repo.delete_all_application_test_data() is True

    assert repo.list_meets(include_archived=True) == []
    assert repo.races == {}
    assert repo.race_athletes == {}
    assert repo.race_sessions == {}
    assert repo.split_events == {}
    assert len(repo.list_templates(include_archived=True)) == 2


def test_delete_missing_records_return_false_safely():
    repo = InMemoryRaceRepository()

    assert repo.delete_meet("missing") is False
    assert repo.delete_race("missing") is False
    assert repo.delete_race_session("missing") is False


def test_session_state_cleanup_after_deletions():
    session = Session()
    initialize_state(session)
    session.selected_meet_id = "meet"
    session.selected_race_id = "race"
    session.active_race_session_id = "session"
    session.selected_results_session_id = "session"
    session.timing_restored_for_race_id = "race"
    session.race_rosters = {"race": [Athlete(name="Runner", athlete_id="a1")]}
    session.athletes = [Athlete(name="Runner", athlete_id="a1")]
    session.race_clock = RaceClock(status="running", start_perf_counter=1.0)

    cleanup_after_session_delete(session, "session")
    assert session.active_race_session_id is None
    assert session.selected_results_session_id is None

    session.selected_race_id = "race"
    cleanup_after_roster_clear(session, "race")
    assert session.race_rosters == {}
    assert session.athletes == []

    session.selected_meet_id = "meet"
    session.selected_race_id = "race"
    cleanup_after_race_delete(session, "race")
    assert session.selected_race_id is None

    session.selected_meet_id = "meet"
    cleanup_after_meet_delete(session, "meet", ["race"])
    assert session.selected_meet_id is None


def test_supabase_delete_methods_filter_by_target_ids():
    class Result:
        def __init__(self, data=None):
            self.data = [] if data is None else data

    class Query:
        def __init__(self, actions, table):
            self.actions = actions
            self.table_name = table

        def select(self, value):
            self.actions.append((self.table_name, "select", value))
            return self

        def delete(self):
            self.actions.append((self.table_name, "delete"))
            return self

        def eq(self, key, value):
            self.actions.append((self.table_name, "eq", key, value))
            return self

        def neq(self, key, value):
            self.actions.append((self.table_name, "neq", key, value))
            return self

        def order(self, key, desc=False):
            self.actions.append((self.table_name, "order", key, desc))
            return self

        def execute(self):
            if self.table_name == "meets":
                return Result([{"id": "meet", "name": "Meet"}])
            if self.table_name == "races":
                return Result([{"id": "race", "meet_id": "meet", "name": "Race", "distance_meters": 800}])
            if self.table_name == "race_sessions":
                return Result([{"id": "session", "race_id": "race"}])
            return Result([])

    class Client:
        def __init__(self):
            self.actions = []

        def table(self, name):
            self.actions.append((name, "table"))
            return Query(self.actions, name)

    from split_tracker.repository import SupabaseRaceRepository

    client = Client()
    repo = SupabaseRaceRepository(client)
    repo.delete_meet("meet")
    repo.delete_race("race")
    repo.delete_race_session("session")
    repo.clear_race_roster("race")

    assert ("meets", "eq", "id", "meet") in client.actions
    assert ("races", "eq", "id", "race") in client.actions
    assert ("race_sessions", "eq", "id", "session") in client.actions
    assert ("race_athletes", "eq", "race_id", "race") in client.actions
