"""Tests for race history and reconstructed results."""

from __future__ import annotations

from datetime import datetime, timezone

from split_tracker.calculations import generate_checkpoints
from split_tracker.models import Athlete
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, SplitEvent
from split_tracker.results import filter_results, reconstruct_results, results_to_frame, summarize_sessions


def make_history_fixture():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Creekside Invitational"))
    boys = repo.create_race(Race(meet_id=meet.id, name="Boys JV", distance_meters=800.0, course_type="Track"))
    girls = repo.create_race(Race(meet_id=meet.id, name="Girls JV", distance_meters=800.0, course_type="Track"))
    checkpoints = generate_checkpoints(race_distance_meters=800.0, mode="Fixed interval", interval_meters=400.0)
    athletes = [
        Athlete(name="Alex", bib_number="1", gender="M", grade="10", team="Creekside", group="JV", athlete_id="a1", display_order=0),
        Athlete(name="Blake", bib_number="2", gender="M", grade="11", team="Creekside", group="JV", athlete_id="a2", display_order=1),
        Athlete(name="Casey", bib_number="3", gender="F", grade="9", team="North", group="Open", athlete_id="a3", display_order=2),
        Athlete(name="Drew", bib_number="4", gender="F", grade="12", team="North", group="Open", athlete_id="a4", display_order=3),
    ]
    repo.replace_race_athletes(boys.id, athletes)
    repo.replace_race_athletes(girls.id, [Athlete(name="Gia", bib_number="1", gender="F", athlete_id="g1")])
    return repo, meet, boys, girls, checkpoints, athletes


def add_event(repo, session, athlete, checkpoint_number, elapsed, order, *, deleted=False, name=None, bib=None):
    return repo.create_split_event(
        SplitEvent(
            race_session_id=session.id,
            athlete_id=athlete,
            athlete_name=name or athlete,
            bib_number=bib or "",
            checkpoint_number=checkpoint_number,
            elapsed_seconds=elapsed,
            event_order=order,
            is_deleted=deleted,
        )
    )


def test_listing_multiple_sessions_and_selecting_history_summary():
    repo, _, boys, _, checkpoints, athletes = make_history_fixture()
    first = repo.create_race_session(RaceSession(race_id=boys.id, status="completed", started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), elapsed_offset_seconds=130.0))
    second = repo.create_race_session(RaceSession(race_id=boys.id, status="completed", started_at=datetime(2026, 1, 2, tzinfo=timezone.utc), elapsed_offset_seconds=125.0))
    add_event(repo, second, "a1", 1, 60.0, 1)
    add_event(repo, second, "a1", 2, 125.0, 2)

    summaries = summarize_sessions(repo, race_id=boys.id, athletes=athletes, checkpoints=checkpoints, race_distance_meters=boys.distance_meters)

    assert [summary.session_id for summary in summaries] == [first.id, second.id]
    selected = next(summary for summary in summaries if summary.session_id == second.id)
    assert selected.active_split_count == 2
    assert selected.finished_athlete_count == 1


def test_reconstructing_finish_results_places_and_ties():
    repo, meet, boys, _, checkpoints, athletes = make_history_fixture()
    session = repo.create_race_session(RaceSession(race_id=boys.id, status="completed"))
    add_event(repo, session, "a1", 1, 60.0, 1)
    add_event(repo, session, "a2", 1, 62.0, 2)
    add_event(repo, session, "a1", 2, 120.0, 3)
    add_event(repo, session, "a2", 2, 120.0, 4)

    rows = reconstruct_results(meet_name=meet.name, race_name=boys.name, session=session, athletes=athletes, checkpoints=checkpoints, race_distance_meters=boys.distance_meters, events=repo.list_active_split_events(session.id))
    finishers = [row for row in rows if row["Status"] == "Finished"]

    assert [row["Athlete"] for row in finishers] == ["Alex", "Blake"]
    assert [row["Overall Place"] for row in finishers] == [1, 1]
    assert [row["Gender Place"] for row in finishers] == [1, 1]
    assert finishers[0]["Finish Time"] == "2:00.00"
    assert finishers[0]["400 m Split"] == "1:00.00"
    assert finishers[0]["Finish Cumulative"] == "2:00.00"


def test_incomplete_dnf_dns_and_deleted_events_excluded():
    repo, meet, boys, _, checkpoints, athletes = make_history_fixture()
    session = repo.create_race_session(RaceSession(race_id=boys.id, status="completed"))
    add_event(repo, session, "a1", 1, 60.0, 1)
    add_event(repo, session, "a1", 2, 130.0, 2, deleted=True)
    add_event(repo, session, "a2", 1, 70.0, 3)
    add_event(repo, session, "a2", 2, 140.0, 4)

    rows = reconstruct_results(meet_name=meet.name, race_name=boys.name, session=session, athletes=athletes, checkpoints=checkpoints, race_distance_meters=boys.distance_meters, events=repo.list_all_split_events(session.id))
    by_name = {row["Athlete"]: row for row in rows}

    assert by_name["Alex"]["Status"] == "DNF"
    assert by_name["Alex"]["Finish Time"] == "—"
    assert by_name["Blake"]["Status"] == "Finished"
    assert by_name["Casey"]["Status"] == "DNS"
    assert by_name["Drew"]["Status"] == "DNS"


def test_in_progress_status_for_active_session_partial_splits():
    repo, meet, boys, _, checkpoints, athletes = make_history_fixture()
    session = repo.create_race_session(RaceSession(race_id=boys.id, status="running"))
    add_event(repo, session, "a1", 1, 60.0, 1)

    rows = reconstruct_results(meet_name=meet.name, race_name=boys.name, session=session, athletes=athletes, checkpoints=checkpoints, race_distance_meters=boys.distance_meters, events=repo.list_active_split_events(session.id))

    assert {row["Athlete"]: row["Status"] for row in rows}["Alex"] == "In Progress"


def test_roster_snapshot_fallback_and_invalid_checkpoint_reference():
    repo, meet, boys, _, checkpoints, _ = make_history_fixture()
    session = repo.create_race_session(RaceSession(race_id=boys.id, status="completed"))
    add_event(repo, session, "missing", 1, 65.0, 1, name="Snapshot Runner", bib="99")
    add_event(repo, session, "missing", 99, 130.0, 2, name="Snapshot Runner", bib="99")

    rows = reconstruct_results(meet_name=meet.name, race_name=boys.name, session=session, athletes=[], checkpoints=checkpoints[1:], race_distance_meters=boys.distance_meters, events=repo.list_active_split_events(session.id))

    assert rows[0]["Athlete"] == "Snapshot Runner"
    assert rows[0]["Bib"] == "99"
    assert rows[0]["Status"] == "Finished"


def test_csv_export_contents_and_filters():
    repo, meet, boys, _, checkpoints, athletes = make_history_fixture()
    session = repo.create_race_session(RaceSession(race_id=boys.id, status="completed"))
    add_event(repo, session, "a1", 1, 60.0, 1)
    add_event(repo, session, "a1", 2, 125.0, 2)

    rows = reconstruct_results(meet_name=meet.name, race_name=boys.name, session=session, athletes=athletes, checkpoints=checkpoints, race_distance_meters=boys.distance_meters, events=repo.list_active_split_events(session.id))
    filtered = filter_results(rows, gender="M", team="Creekside", category="JV", status="Finished")
    csv_text = results_to_frame(filtered, formatted_for_export=True).to_csv(index=False)

    assert "Meet,Race,Session ID,Athlete,Bib" in csv_text
    assert "Creekside Invitational" in csv_text
    assert "Alex" in csv_text
    assert "Finish Time Seconds" not in csv_text
    assert "2:05.00" in csv_text


def test_race_specific_results_isolation():
    repo, meet, boys, girls, checkpoints, athletes = make_history_fixture()
    boys_session = repo.create_race_session(RaceSession(race_id=boys.id, status="completed"))
    girls_session = repo.create_race_session(RaceSession(race_id=girls.id, status="completed"))
    add_event(repo, boys_session, "a1", 1, 60.0, 1)
    add_event(repo, boys_session, "a1", 2, 120.0, 2)
    add_event(repo, girls_session, "g1", 1, 80.0, 1)

    boys_rows = reconstruct_results(meet_name=meet.name, race_name=boys.name, session=boys_session, athletes=athletes, checkpoints=checkpoints, race_distance_meters=boys.distance_meters, events=repo.list_active_split_events(boys_session.id))
    girls_rows = reconstruct_results(meet_name=meet.name, race_name=girls.name, session=girls_session, athletes=repo.list_race_athletes(girls.id, include_inactive=True), checkpoints=checkpoints, race_distance_meters=girls.distance_meters, events=repo.list_active_split_events(girls_session.id))

    assert "Alex" in {row["Athlete"] for row in boys_rows}
    assert "Gia" in {row["Athlete"] for row in girls_rows}
    assert "Gia" not in {row["Athlete"] for row in boys_rows}
