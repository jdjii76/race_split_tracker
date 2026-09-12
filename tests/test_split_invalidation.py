"""Post-race split removal, projection, audit, and authorization tests."""
from datetime import date
from pathlib import Path

import pytest

from split_tracker.analytics import calculate_personal_records, calculate_segment_paces, compute_team_checkpoint_ranks
from split_tracker.calculations import derive_gap_estimates
from split_tracker.auth import AppIdentity
from split_tracker.models import Athlete, Checkpoint
from split_tracker.progression import get_completed_results
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, RepositoryError, SplitEvent
from split_tracker.results import printable_results_html, reconstruct_results, results_to_frame
from split_tracker.split_invalidation import remove_split_from_results


COACH = AppIdentity("coach-id", "coach@kmhs.test", "coach")
ADMIN = AppIdentity("admin-id", "admin@kmhs.test", "admin")
TIMER = AppIdentity("timer-id", "timer@kmhs.test", "timer")


def fixture():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet("Invite", meet_date=date(2026, 9, 12)))
    race = repo.create_race(Race(meet.id, "Varsity 5K", 5000))
    athletes = [Athlete("Benjamin Valdivieso", athlete_id="ben"), Athlete("Alex Runner", athlete_id="alex")]
    repo.replace_race_athletes(race.id, athletes)
    session = repo.create_race_session(RaceSession(race.id, status="completed"))
    checkpoints = [Checkpoint(1, "Mile 1", 1609.344), Checkpoint(2, "Mile 2", 3218.688),
                   Checkpoint(3, "Mile 3", 4828.032), Checkpoint(4, "Finish", 5000, True)]
    repo.create_race_session_checkpoints(session.id, checkpoints)
    values = {"ben": (356, 719, 1140.51, 1184), "alex": (360, 725, 1135, 1190)}
    events = {}
    order = 0
    for athlete in athletes:
        for checkpoint, elapsed in zip(checkpoints, values[athlete.athlete_id]):
            order += 1
            event = repo.create_split_event(SplitEvent(
                session.id, athlete.athlete_id, checkpoint.number, elapsed, order,
                athlete_name=athlete.name, checkpoint_label=checkpoint.label,
                device_id="mile-station", capture_mode="pack",
            ))
            events[(athlete.athlete_id, checkpoint.number)] = event
    return repo, meet, race, session, athletes, checkpoints, events


def reconstructed(repo, meet, race, session, athletes, checkpoints):
    return reconstruct_results(
        meet_name=meet.name, race_name=race.name, session=session, athletes=athletes,
        checkpoints=checkpoints, race_distance_meters=race.distance_meters,
        events=repo.list_active_split_events(session.id),
    )


def test_remove_split_is_append_only_and_updates_every_canonical_projection():
    repo, meet, race, session, athletes, checkpoints, events = fixture()
    original = events[("ben", 3)]

    correction = remove_split_from_results(repo, original, "Unofficial Mile 3 split", COACH)

    history = repo.list_all_split_events(session.id)
    assert original in history and not original.is_deleted
    assert correction.event_type == "split_voided" and correction.target_event_id == original.id
    assert correction.correction_type == "removed_from_results"
    assert correction.reason == "Unofficial Mile 3 split" and correction.corrected_by == COACH.user_id
    assert original.device_id == "mile-station" and original.elapsed_seconds == 1140.51
    assert original not in repo.list_active_split_events(session.id)

    rows = reconstructed(repo, meet, race, session, athletes, checkpoints)
    ben = next(row for row in rows if row["Athlete ID"] == "ben")
    assert ben["Mile 3 Elapsed"] == "—" and ben["Mile 3 Split"] == "—"
    assert ben["Finish Elapsed"] == "19:44.00" and ben["Finish Split"] == "—"
    csv = results_to_frame(rows, formatted_for_export=True).to_csv(index=False)
    printable = printable_results_html(meet.name, race.name, rows)
    assert "Mile 3 Elapsed" in csv and "5:56.00 / 6:03.00 / — / —" in csv
    assert "5:56.00 / 6:03.00 / — / —" in printable

    projected = get_completed_results(repo)
    ben_result = next(result for result in projected if result.athlete_id == "ben")
    mile_three = next(split for split in ben_result.splits if split["label"] == "Mile 3")
    assert mile_three["cumulative"] is None and mile_three["segment"] is None
    ranks = compute_team_checkpoint_ranks(projected, checkpoints)
    assert ranks["ben"][2] is None and ranks["alex"][2] == 1
    gaps = derive_gap_estimates(checkpoints, {checkpoint.number: next(
        split["cumulative"] for split in ben_result.splits if split["label"] == checkpoint.label
    ) for checkpoint in checkpoints})
    assert gaps.combined_intervals[0].value_seconds == pytest.approx(1184 - 719)
    assert sum(item.value_seconds for item in gaps.estimated_segments) == pytest.approx(1184 - 719)
    # Estimates are a separate contract and never enter recorded pace or PR inputs.
    assert len(calculate_segment_paces(ben_result)) == 2
    assert calculate_personal_records([ben_result], [])[0].is_first


def test_reason_role_duplicate_and_finish_safety():
    repo, _, _, session, _, _, events = fixture()
    mile = events[("ben", 3)]
    with pytest.raises(RepositoryError, match="reason is required"):
        remove_split_from_results(repo, mile, "   ", COACH)
    with pytest.raises(RepositoryError, match="coach or admin"):
        remove_split_from_results(repo, mile, "Bad tap", TIMER)
    with pytest.raises(RepositoryError, match="Finish results"):
        remove_split_from_results(repo, events[("ben", 4)], "Bad finish", ADMIN, is_finish=True)
    remove_split_from_results(repo, mile, "Bad tap", ADMIN)
    with pytest.raises(RepositoryError, match="no longer active"):
        remove_split_from_results(repo, mile, "Duplicate", COACH)


def test_remove_split_migration_is_append_only_reasoned_and_server_authorized():
    sql = Path("supabase/migrations/035_remove_split_from_results.sql").read_text().lower()
    assert "require_app_role(array['coach','admin'])" in sql
    assert "a correction reason is required" in sql and "trim(p_reason)" in sql
    assert "event_type,target_event_id,reason" in sql and "'split_voided'" in sql
    assert "'removed_from_results'" in sql
    assert "finish results must be corrected through manage results" in sql
    assert "for update" in sql and "no longer active" in sql
    assert "delete from public.split_events" not in sql and "update public.split_events" not in sql
    assert "auth.uid()::text" in sql
