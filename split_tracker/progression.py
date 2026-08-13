"""Derived athlete and team progression projections from finalized timing events."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import fmean, pstdev

from split_tracker.models import Checkpoint
from split_tracker.results import reconstruct_results

METERS_PER_MILE = 1609.344
EVEN_RELATIVE_SPREAD = .03
DIRECTIONAL_RELATIVE_CHANGE = .03


@dataclass(frozen=True)
class AthleteResult:
    athlete_id: str; session_id: str; race_id: str; race_name: str; meet_name: str
    race_date: date | None; distance_meters: float; status: str
    finish_seconds: float | None; place: int | None; course_id: str | None; course_name: str
    splits: tuple[dict[str, object], ...] = ()
    athlete_name: str = ""
    classification: str = ""
    gender: str = ""
    race_category: str = ""
    is_test: bool = False

    @property
    def season(self) -> int | None: return self.race_date.year if self.race_date else None
    @property
    def pace_seconds_per_mile(self) -> float | None:
        return self.finish_seconds / (self.distance_meters / METERS_PER_MILE) if self.finish_seconds and self.distance_meters > 0 else None


def filter_results(results, *, season=None, distance_meters=None):
    return [r for r in results if (season is None or r.season == season) and
            (distance_meters is None or abs(r.distance_meters-distance_meters) < .5)]


def season_summary(results, *, season=None, distance_meters=None):
    selected = filter_results(results, season=season, distance_meters=distance_meters)
    finished = sorted((r for r in selected if r.status == "Finished" and r.finish_seconds is not None), key=lambda r: (r.race_date or date.min, r.session_id))
    best = min(finished, key=lambda r: r.finish_seconds) if finished else None
    return {"season_pr": best.finish_seconds if best else None,
            "best_pace": min((r.pace_seconds_per_mile for r in finished if r.pace_seconds_per_mile), default=None),
            "races": len(selected), "best_place": min((r.place for r in finished if r.place), default=None),
            "most_recent": max(selected, key=lambda r: (r.race_date or date.min, r.session_id), default=None),
            "improvement": max(0., finished[0].finish_seconds-best.finish_seconds) if best and finished else None}


def course_bests(results):
    best = {}
    for result in results:
        if result.course_id and result.status == "Finished" and result.finish_seconds is not None:
            key = (result.course_id, result.distance_meters)
            if key not in best or result.finish_seconds < best[key].finish_seconds: best[key] = result
    return sorted(best.values(), key=lambda r: (r.course_name.casefold(), r.distance_meters))


def split_consistency(segment_seconds):
    values = [float(value) for value in segment_seconds if value is not None and value > 0]
    if len(values) < 2: return None
    average, spread = fmean(values), max(values)-min(values)
    relative = spread / average
    change = (fmean(values[len(values)//2:])-fmean(values[:(len(values)+1)//2])) / average
    label = "Even" if relative <= EVEN_RELATIVE_SPREAD else ("Positive Split" if change >= DIRECTIONAL_RELATIVE_CHANGE else ("Negative Split" if change <= -DIRECTIONAL_RELATIVE_CHANGE else "Variable"))
    return {"fastest": min(values), "slowest": max(values), "spread": spread, "average": average,
            "deviation": pstdev(values), "first_half": fmean(values[:(len(values)+1)//2]),
            "second_half": fmean(values[len(values)//2:]), "label": label}


def team_progress(results, athletes, *, season=None, distance_meters=None, include_archived=False):
    rows=[]
    for athlete in athletes:
        if athlete.status == "archived" and not include_archived: continue
        history=sorted(filter_results([r for r in results if r.athlete_id == athlete.id], season=season, distance_meters=distance_meters), key=lambda r:(r.race_date or date.min,r.session_id))
        finished=[r for r in history if r.status == "Finished" and r.finish_seconds is not None]
        if not history: continue
        summary=season_summary(history, season=season, distance_meters=distance_meters)
        rows.append({"athlete": athlete, "season_best": summary["season_pr"], "improvement": summary["improvement"],
                     "previous": finished[-2] if len(finished)>1 else None, "latest": history[-1]})
    return rows


def get_completed_results(repository, athlete_id=None):
    """Build canonical history. Queries are batched by meet/race, never athlete-by-race."""
    meets=repository.list_meets(include_archived=True); meet_by_id={m.id:m for m in meets}
    races=[r for m in meets for r in repository.list_races_for_meet(m.id)]
    sessions=repository.list_race_sessions_for_races([r.id for r in races]); race_by_id={r.id:r for r in races}
    courses={c.id:c for c in repository.list_courses()}; output=[]
    for session in sessions:
        if session.status != "completed": continue
        race=race_by_id[session.race_id]; meet=meet_by_id[race.meet_id]
        roster=repository.list_race_athletes(race.id, include_inactive=True)
        if athlete_id and not any(a.athlete_id == athlete_id for a in roster): continue
        cps=[Checkpoint(number=c.checkpoint_sequence,label=c.label,distance_meters=c.distance_meters,is_finish=c.is_finish) for c in repository.list_race_session_checkpoints(session.id)]
        events=repository.list_active_split_events(session.id)
        rows=reconstruct_results(meet_name=meet.name,race_name=race.name,session=session,athletes=roster,checkpoints=cps,
             race_distance_meters=race.distance_meters,events=events,outcomes=repository.list_race_athlete_outcomes(session.id))
        for row in rows:
            if athlete_id and row["Athlete ID"] != athlete_id: continue
            athlete_splits=[]; previous=0.
            for cp in cps:
                event=next((e for e in events if e.athlete_id==row["Athlete ID"] and e.checkpoint_number==cp.number),None)
                if event:
                    athlete_splits.append({"label":cp.label,"distance_meters":cp.distance_meters,"cumulative":event.elapsed_seconds,"segment":event.elapsed_seconds-previous})
                    previous=event.elapsed_seconds
            course=courses.get(race.course_id)
            output.append(AthleteResult(str(row["Athlete ID"]),session.id,race.id,race.name,meet.name,meet.meet_date,race.distance_meters,str(row["Status"]),row["Finish Time Seconds"],row["Overall Place"],race.course_id,course.course_name if course else "",tuple(athlete_splits),str(row["Athlete"]),str(row.get("Category/Group") or row.get("Team") or ""),str(row.get("Gender") or ""),race.race_category,race.name.lstrip().upper().startswith("TEST")))
    return sorted(output,key=lambda r:(r.race_date or date.min,r.session_id),reverse=True)
