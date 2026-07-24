"""Tests for race-scoped roster persistence and session-state caching."""

from __future__ import annotations

from split_tracker.models import Athlete
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, SupabaseRaceRepository, _athlete_from_row, _athlete_to_row
from split_tracker.state import initialize_state, load_race_into_setup, replace_setup


class Session(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


def make_two_races():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Creekside Invitational"))
    boys = repo.create_race(Race(meet_id=meet.id, name="Boys JV", distance_meters=5000.0))
    girls = repo.create_race(Race(meet_id=meet.id, name="Girls JV", distance_meters=5000.0, display_order=1))
    return repo, meet, boys, girls


def make_session(repo):
    session = Session()
    initialize_state(session)
    session.repository = repo
    session.repository_result = None
    session.active_race_session_id = None
    session.timing_restored_for_race_id = None
    return session


def test_two_races_keep_independent_rosters_when_switching():
    repo, meet, boys, girls = make_two_races()
    session = make_session(repo)
    boys_roster = [Athlete(name="Ben", bib_number="1", gender="M", grade="10", team="Creekside", athlete_id="boys-1")]
    girls_roster = [Athlete(name="Gia", bib_number="1", gender="F", grade="11", team="Creekside", athlete_id="girls-1")]

    load_race_into_setup(session, meet, boys)
    replace_setup(session, session.meet_config, boys_roster)
    load_race_into_setup(session, meet, girls)
    assert session.athletes == []

    replace_setup(session, session.meet_config, girls_roster)
    load_race_into_setup(session, meet, boys)
    assert [athlete.name for athlete in session.athletes] == ["Ben"]
    assert session.athletes[0].bib_number == "1"

    load_race_into_setup(session, meet, girls)
    assert [athlete.name for athlete in session.athletes] == ["Gia"]
    assert session.athletes[0].bib_number == "1"


def test_updating_and_deleting_one_race_roster_does_not_change_other_race():
    repo, meet, boys, girls = make_two_races()
    boys_roster = [Athlete(name="Ben", athlete_id="boys-1"), Athlete(name="Bo", athlete_id="boys-2")]
    girls_roster = [Athlete(name="Gia", athlete_id="girls-1")]
    repo.replace_race_athletes(boys.id, boys_roster)
    repo.replace_race_athletes(girls.id, girls_roster)

    repo.replace_race_athletes(boys.id, [Athlete(name="Ben Updated", athlete_id="boys-1")])
    repo.delete_race_athlete(boys.id, "boys-1")

    assert repo.list_race_athletes(boys.id, include_inactive=True) == []
    assert [athlete.name for athlete in repo.list_race_athletes(girls.id, include_inactive=True)] == ["Gia"]


def test_same_athlete_id_or_bib_can_exist_in_different_races():
    repo, _, boys, girls = make_two_races()
    repo.replace_race_athletes(boys.id, [Athlete(name="Jordan Boys", bib_number="7", athlete_id="shared-athlete")])
    repo.replace_race_athletes(girls.id, [Athlete(name="Jordan Girls", bib_number="7", athlete_id="shared-athlete")])

    assert [athlete.name for athlete in repo.list_race_athletes(boys.id)] == ["Jordan Boys"]
    assert [athlete.name for athlete in repo.list_race_athletes(girls.id)] == ["Jordan Girls"]


def test_live_timing_receives_roster_for_selected_race():
    repo, meet, boys, girls = make_two_races()
    session = make_session(repo)
    repo.replace_race_athletes(boys.id, [Athlete(name="Ben", athlete_id="boys-1")])
    repo.replace_race_athletes(girls.id, [Athlete(name="Gia", athlete_id="girls-1")])

    load_race_into_setup(session, meet, boys)
    assert [athlete.athlete_id for athlete in session.athletes] == ["boys-1"]

    load_race_into_setup(session, meet, girls)
    assert [athlete.athlete_id for athlete in session.athletes] == ["girls-1"]


def test_race_scoped_roster_cache_survives_rerun_simulation():
    repo, meet, boys, girls = make_two_races()
    session = make_session(repo)
    load_race_into_setup(session, meet, boys)
    replace_setup(session, session.meet_config, [Athlete(name="Ben", athlete_id="boys-1")])
    load_race_into_setup(session, meet, girls)
    replace_setup(session, session.meet_config, [Athlete(name="Gia", athlete_id="girls-1")])

    rerun = make_session(repo)
    rerun.race_rosters = session.race_rosters
    load_race_into_setup(rerun, meet, boys)
    assert [athlete.name for athlete in rerun.athletes] == ["Ben"]
    load_race_into_setup(rerun, meet, girls)
    assert [athlete.name for athlete in rerun.athletes] == ["Gia"]


def test_athlete_row_serialization_includes_race_specific_fields():
    athlete = Athlete(
        name="Gia",
        bib_number="12",
        gender="F",
        grade="11",
        team="Creekside",
        target_finish_time_seconds=1200.0,
        target_pace_seconds_per_mile=386.0,
        group="Varsity",
        display_order=3,
        active=False,
        athlete_id="00000000-0000-0000-0000-000000000301",
    )

    row = _athlete_to_row("race-1", athlete)
    restored = _athlete_from_row({**row, "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"})

    assert row["race_id"] == "race-1"
    assert row["team"] == "Creekside"
    assert restored.gender == "F"
    assert restored.grade == "11"
    assert not restored.active


def test_supabase_roster_operations_filter_by_race_id():
    class Result:
        data = []

    class Query:
        def __init__(self, actions):
            self.actions = actions

        def select(self, value):
            self.actions.append(("select", value))
            return self

        def delete(self):
            self.actions.append(("delete",))
            return self

        def eq(self, key, value):
            self.actions.append(("eq", key, value))
            return self

        def order(self, key, desc=False):
            self.actions.append(("order", key, desc))
            return self

        def execute(self):
            return Result()

    class Client:
        def __init__(self):
            self.actions = []

        def table(self, name):
            self.actions.append(("table", name))
            return Query(self.actions)

    client = Client()
    repo = SupabaseRaceRepository(client)

    repo.list_race_athletes("race-1")
    repo.delete_race_athlete("race-1", "athlete-1")

    assert ("eq", "race_id", "race-1") in client.actions
    assert ("eq", "active", True) in client.actions
    assert ("eq", "athlete_id", "athlete-1") in client.actions
