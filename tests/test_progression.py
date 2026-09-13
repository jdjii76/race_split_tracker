from datetime import date
from split_tracker.models import PermanentAthlete
from split_tracker.progression import AthleteResult, course_bests, season_summary, split_consistency, team_progress

def result(day, seconds, *, distance=5000, status="Finished", course="c1", athlete="a"):
    return AthleteResult(athlete,str(day),f"r{day}","Varsity","Meet",date(2026,8,day),distance,status,seconds,day,course,"Course",())

def test_summary_is_distance_and_dnf_aware():
    rows=[result(1,1200),result(8,1150),result(9,None,status="DNF"),result(10,600,distance=3200)]
    summary=season_summary(rows,season=2026,distance_meters=5000)
    assert summary["season_pr"] == 1150 and summary["improvement"] == 50 and summary["races"] == 3
    assert round(summary["best_pace"],3) == round(1150/(5000/1609.344),3)

def test_seasons_do_not_contaminate_each_other():
    old=result(1,1000); old=old.__class__(**{**old.__dict__,"race_date":date(2025,8,1)})
    assert season_summary([old,result(2,1200)],season=2026,distance_meters=5000)["season_pr"] == 1200

def test_course_best_uses_stable_id_and_distance():
    rows=[result(1,1200),result(2,1180),result(3,600,distance=3200),result(4,1100,course="c2")]
    assert {(r.course_id,r.distance_meters,r.finish_seconds) for r in course_bests(rows)} == {("c1",5000,1180),("c1",3200,600),("c2",5000,1100)}

def test_split_consistency_and_insufficient_data():
    assert split_consistency([360]) is None
    assert split_consistency([360,361,359])["label"] == "Even"
    assert split_consistency([350,370,390])["label"] == "Positive Split"
    assert split_consistency([390,370,350])["label"] == "Negative Split"

def test_team_progress_previous_latest_and_archive():
    active=PermanentAthlete("A","Runner",id="a",team_division="Swing")
    archived=PermanentAthlete("Old","Runner",id="b",status="archived")
    rows=team_progress([result(1,1200),result(2,1150)], [active,archived],season=2026,distance_meters=5000)
    assert len(rows)==1 and rows[0]["improvement"]==50 and rows[0]["previous"].finish_seconds==1200 and rows[0]["latest"].finish_seconds==1150
