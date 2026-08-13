from datetime import date

from split_tracker.analytics import (calculate_pace_profile, calculate_personal_records,
    calculate_segment_paces, calculate_team_pace_profile, calculate_team_spread,
    calculate_team_top_n, calculate_top5_gaps, compare_team_races, find_previous_comparable_race)
from split_tracker.models import Athlete, Checkpoint
from split_tracker.progression import AthleteResult, get_completed_results
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, SplitEvent


def result(day, seconds, *, athlete="a", distance=5000, status="Finished", race="race", session=None,
           category="BV", classification="BV", splits=(), test=False):
    return AthleteResult(athlete,session or f"s{day}",race,f"Race {race}","Meet",date(2026,8,day),distance,
                         status,seconds,1,None,"",tuple(splits),athlete,classification,"B",category,test)


def splits(early=360, late=350, middle=370):
    return ({"distance_meters":1609.344,"cumulative":early,"segment":early},
            {"distance_meters":3218.688,"cumulative":early+middle,"segment":middle},
            {"distance_meters":5000,"cumulative":early+middle+late,"segment":late})


def test_personal_records_same_distance_first_non_pr_and_dnf():
    history=[result(1,1200),result(2,700,distance=3200),result(3,1190,athlete="b")]
    records=calculate_personal_records([result(8,1170),result(8,1210,athlete="b"),
        result(8,1180,athlete="new"),result(8,None,athlete="dnf",status="DNF")],history)
    assert records[0].is_pr and records[0].previous_best==1200 and records[0].improvement==30
    assert not records[1].is_pr and records[1].previous_best==1190
    assert records[2].is_first and not records[2].is_pr
    assert not records[3].is_pr and not records[3].is_first


def test_segment_paces_negative_even_fade_and_uneven_distances():
    negative=calculate_pace_profile(result(8,1080,splits=splits(360,330)))
    final_segment_miles=(5000-3218.688)/1609.344
    even=calculate_pace_profile(result(8,1080,splits=splits(360,360*final_segment_miles)))
    fade=calculate_pace_profile(result(8,1080,splits=splits(340,390)))
    assert negative.change < 0 and abs(even.change) < .001 and fade.change > 0
    uneven=result(8,900,splits=({"distance_meters":1000,"cumulative":240},
        {"distance_meters":2500,"cumulative":630},{"distance_meters":5000,"cumulative":1300}))
    paces=calculate_segment_paces(uneven)
    assert len(paces)==3 and round(paces[0],3)==round(240/(1000/1609.344),3)


def test_missing_and_zero_length_segments_are_safe():
    missing=result(8,900,splits=({"distance_meters":1609.344,"cumulative":360},))
    invalid=result(8,900,splits=({"distance_meters":0,"cumulative":10},
        {"distance_meters":1609.344,"cumulative":360}))
    assert calculate_pace_profile(missing) is None
    assert calculate_segment_paces(invalid)==[350.0]


def test_top7_swing_and_dnf_and_spreads_and_gaps():
    rows=[result(8,1000+i*10,athlete=str(i),classification="Swing" if i==2 else "BV") for i in range(9)]
    rows.append(result(8,None,athlete="dnf",status="DNF"))
    top=calculate_team_top_n(rows)
    assert len(top)==7 and top[2].classification=="Swing" and all(r.status=="Finished" for r in top)
    assert calculate_team_spread(rows,5)==40 and calculate_team_spread(rows,7)==60
    assert calculate_top5_gaps(rows)==[10,10,10,10]
    assert calculate_team_spread(rows[:4],5) is None and calculate_team_spread(rows[:6],7) is None


def test_previous_comparable_race_selection_and_comparison():
    current=result(10,1100,race="current",category="BV")
    prior=result(8,1150,race="prior",category="BV")
    older=result(3,1160,race="older",category="BV")
    wrong_distance=result(9,700,race="short",distance=3200,category="BV")
    wrong_group=result(9,1090,race="girls",category="GV")
    provisional=result(9,1080,race="provisional",category="BV")  # not supplied: projections contain completed only
    found=find_previous_comparable_race(current,[current,older,prior,wrong_distance,wrong_group])
    assert found and found[0].race_id=="prior"
    assert find_previous_comparable_race(current,[current,wrong_distance,wrong_group]) is None
    comparison=compare_team_races([prior],[current],[older,prior,current])
    assert comparison[0]["change"]==-50
    assert provisional.race_id == "provisional"


def test_team_pace_profile_excludes_missing_splits():
    rows=[result(8,1100,athlete="a",splits=splits()),result(8,1120,athlete="b",splits=())]
    profile=calculate_team_pace_profile(rows)
    assert profile["valid"]==1 and profile["total"]==2


def test_completed_projection_uses_replacement_and_preserves_audit():
    repo=InMemoryRaceRepository(); meet=repo.create_meet(Meet(name="Invite",meet_date=date(2026,8,8)))
    race=repo.create_race(Race(meet_id=meet.id,name="Boys Varsity",race_category="BV",distance_meters=3200))
    athlete=Athlete(name="Runner",athlete_id="runner",team="BV",group="Swing")
    repo.replace_race_athletes(race.id,[athlete]); session=repo.create_race_session(RaceSession(race_id=race.id,status="paused"))
    repo.create_race_session_checkpoints(session.id,[Checkpoint(1,"Mile 1",1609.344),Checkpoint(2,"Finish",3200,True)])
    repo.create_split_event(SplitEvent(race_session_id=session.id,athlete_id="runner",checkpoint_number=1,elapsed_seconds=360,event_order=1))
    original=repo.create_split_event(SplitEvent(race_session_id=session.id,athlete_id="runner",checkpoint_number=2,elapsed_seconds=800,event_order=2))
    voided=repo.invalidate_split_event(original.id,session.id,"runner",2,"Coach")
    replacement=SplitEvent(race_session_id=session.id,athlete_id="runner",checkpoint_number=2,elapsed_seconds=750,event_order=voided.event_order+1,corrects_event_id=original.id,event_type="split_corrected")
    repo.split_events[replacement.id]=replacement
    repo.update_race_session(RaceSession(**{**session.__dict__,"status":"completed"}))
    projected=get_completed_results(repo,"runner")
    assert projected[0].finish_seconds==750
    assert {original.id,replacement.id}.issubset({event.id for event in repo.list_all_split_events(session.id)})
