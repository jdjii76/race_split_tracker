from dataclasses import replace

import pytest

from split_tracker.formatting import parse_time_to_seconds
from split_tracker.models import Athlete, Checkpoint
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, RepositoryError, ResultEvent, SplitEvent
from split_tracker.results import reconstruct_results


def completed_repo():
    repo = InMemoryRaceRepository(); meet = repo.create_meet(Meet("Meet")); race = repo.create_race(Race(meet.id,"5K",5000))
    athlete = Athlete("a1", "Emma Smith", team="KMHS"); repo.replace_race_athletes(race.id,[athlete])
    session = repo.create_race_session(RaceSession(race.id, status="completed", ended_at=Meet("x").created_at))
    checkpoints=[Checkpoint(1,"Mile 1",1609.344),Checkpoint(2,"Finish",5000,True)]
    repo.create_race_session_checkpoints(session.id,checkpoints)
    return repo,meet,race,athlete,session,checkpoints


def rows(repo, meet, race, athlete, session, checkpoints):
    return reconstruct_results(meet_name=meet.name,race_name=race.name,session=session,athletes=[athlete],checkpoints=checkpoints,
        race_distance_meters=race.distance_meters,events=repo.list_active_split_events(session.id),
        outcomes=repo.list_race_athlete_outcomes(session.id),result_events=repo.list_result_events(session.id))


def test_manual_finish_and_multiple_official_corrections_are_canonical():
    repo,meet,race,athlete,session,cps=completed_repo()
    first=repo.save_post_race_result(ResultEvent(session.id,athlete.athlete_id,"finished","manual",finish_seconds=1294.8,splits={1:390}))
    second=repo.save_post_race_result(ResultEvent(session.id,athlete.athlete_id,"finished","official",finish_seconds=1293.92,supersedes_id=first.id))
    repo.save_post_race_result(ResultEvent(session.id,athlete.athlete_id,"finished","official",finish_seconds=1293.88,supersedes_id=second.id))
    result=rows(repo,meet,race,athlete,session,cps)
    assert len(result)==1 and result[0]["Finish Time Seconds"]==1293.88 and result[0]["Place"]==1
    assert len(repo.list_result_events(session.id,athlete.athlete_id))==3
    unchanged=repo.get_race_session(session.id)
    assert unchanged.status=="completed" and unchanged.ended_at==session.ended_at


def test_manual_dnf_has_no_time_or_place():
    repo,meet,race,athlete,session,cps=completed_repo()
    repo.save_post_race_result(ResultEvent(session.id,athlete.athlete_id,"dnf","manual"))
    result=rows(repo,meet,race,athlete,session,cps)[0]
    assert result["Status"]=="DNF" and result["Finish Time Seconds"] is None and result["Place"]=="—"


@pytest.mark.parametrize("value", ["", "0", "-1", "21:99", "1:62:15", "21:34.999", "nope"])
def test_invalid_duration_strings(value): assert parse_time_to_seconds(value) is None


def test_result_validation_and_chronology():
    repo,_,_,athlete,session,_=completed_repo()
    with pytest.raises(RepositoryError): repo.save_post_race_result(ResultEvent(session.id,athlete.athlete_id,"finished","manual"))
    with pytest.raises(RepositoryError): repo.save_post_race_result(ResultEvent(session.id,athlete.athlete_id,"finished","manual",finish_seconds=100,splits={1:80,2:70}))


def test_forgiving_duration_formats():
    assert [parse_time_to_seconds(v) for v in ("21:34","21:34.6","21:34.62","1:02:15","1:02:15.4")]==[1294,1294.6,1294.62,3735,3735.4]
