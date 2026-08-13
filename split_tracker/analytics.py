"""Pure, read-only post-race analytics derived from finalized result projections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import fmean
from typing import Iterable

from split_tracker.progression import AthleteResult, METERS_PER_MILE

DISTANCE_TOLERANCE_METERS = .5


@dataclass(frozen=True)
class PersonalRecord:
    result: AthleteResult
    previous_best: float | None
    is_pr: bool
    is_first: bool
    improvement: float | None


@dataclass(frozen=True)
class PaceProfile:
    early_pace: float
    late_pace: float

    @property
    def change(self) -> float:
        """Positive is a fade; negative is a negative split."""
        return self.late_pace - self.early_pace


def same_distance(left: float, right: float) -> bool:
    return abs(left - right) < DISTANCE_TOLERANCE_METERS


def calculate_segment_paces(result: AthleteResult) -> list[float]:
    """Normalize every positive, measurable checkpoint interval to seconds/mile."""
    paces: list[float] = []
    previous_distance = previous_time = 0.0
    for split in sorted(result.splits, key=lambda item: float(item["distance_meters"])):
        distance, elapsed = float(split["distance_meters"]), float(split["cumulative"])
        distance_delta, time_delta = distance - previous_distance, elapsed - previous_time
        if distance_delta > 0 and time_delta > 0:
            paces.append(time_delta / (distance_delta / METERS_PER_MILE))
        previous_distance, previous_time = distance, elapsed
    return paces


def calculate_pace_profile(result: AthleteResult) -> PaceProfile | None:
    paces = calculate_segment_paces(result)
    return PaceProfile(paces[0], paces[-1]) if len(paces) >= 2 else None


def calculate_personal_records(current: Iterable[AthleteResult], history: Iterable[AthleteResult]) -> list[PersonalRecord]:
    history = list(history)
    records = []
    for result in current:
        if result.status != "Finished" or result.finish_seconds is None:
            records.append(PersonalRecord(result, None, False, False, None)); continue
        prior = [item.finish_seconds for item in history if item.athlete_id == result.athlete_id
                 and item.session_id != result.session_id and not item.is_test and item.status == "Finished"
                 and item.finish_seconds is not None and same_distance(item.distance_meters, result.distance_meters)
                 and _is_prior(item, result)]
        previous = min(prior) if prior else None
        records.append(PersonalRecord(result, previous, previous is not None and result.finish_seconds < previous,
                                      previous is None, previous-result.finish_seconds if previous is not None and result.finish_seconds < previous else None))
    return records


def calculate_team_top_n(results: Iterable[AthleteResult], n: int = 7) -> list[AthleteResult]:
    """The selected race is eligibility: Swing remains Swing but may rank in its varsity race."""
    return sorted((r for r in results if r.status == "Finished" and r.finish_seconds is not None),
                  key=lambda r: (r.finish_seconds, r.place or 10**9, r.athlete_id))[:n]


def calculate_team_spread(finishers: Iterable[AthleteResult], size: int) -> float | None:
    ranked = calculate_team_top_n(finishers, max(size, 7))
    return ranked[size-1].finish_seconds-ranked[0].finish_seconds if len(ranked) >= size else None


def calculate_top5_gaps(finishers: Iterable[AthleteResult]) -> list[float]:
    ranked = calculate_team_top_n(finishers, 5)
    return [ranked[index+1].finish_seconds-ranked[index].finish_seconds for index in range(len(ranked)-1)]


def calculate_team_pace_profile(results: Iterable[AthleteResult]) -> dict[str, float | int | None]:
    results = list(results); profiles = [profile for result in results if (profile := calculate_pace_profile(result))]
    early = fmean(profile.early_pace for profile in profiles) if profiles else None
    late = fmean(profile.late_pace for profile in profiles) if profiles else None
    return {"early": early, "late": late, "change": late-early if early is not None and late is not None else None,
            "valid": len(profiles), "total": len(results)}


def find_previous_comparable_race(current: AthleteResult, history: Iterable[AthleteResult]) -> list[AthleteResult] | None:
    candidates: dict[tuple[str, str], list[AthleteResult]] = {}
    current_group = _race_group(current)
    for result in history:
        if result.session_id == current.session_id or result.is_test or not _is_prior(result, current): continue
        if not same_distance(result.distance_meters, current.distance_meters) or _race_group(result) != current_group: continue
        candidates.setdefault((result.race_id, result.session_id), []).append(result)
    if not candidates: return None
    return max(candidates.values(), key=lambda rows: (rows[0].race_date or date.min, rows[0].session_id))


def race_metrics(results: Iterable[AthleteResult], history: Iterable[AthleteResult] = ()) -> dict[str, float | int | None]:
    rows=list(results); finishers=calculate_team_top_n(rows, len(rows)); pace=calculate_team_pace_profile(finishers)
    prs=calculate_personal_records(finishers, history)
    return {"finishers":len(finishers), "prs":sum(record.is_pr for record in prs),
            "average_finish":fmean(r.finish_seconds for r in finishers) if finishers else None,
            "spread_5":calculate_team_spread(finishers,5), "spread_7":calculate_team_spread(finishers,7),
            "early":pace["early"], "late":pace["late"], "pace_change":pace["change"],
            "valid_paces":pace["valid"]}


def compare_team_races(previous: Iterable[AthleteResult], current: Iterable[AthleteResult], history: Iterable[AthleteResult] = ()) -> list[dict[str, object]]:
    old,new=race_metrics(previous,history),race_metrics(current,history)
    keys=("average_finish","spread_5","spread_7","early","late","prs","finishers")
    return [{"metric":key,"previous":old[key],"current":new[key],
             "change":new[key]-old[key] if new[key] is not None and old[key] is not None else None} for key in keys]


def _is_prior(candidate: AthleteResult, current: AthleteResult) -> bool:
    return (candidate.race_date or date.min, candidate.session_id) < (current.race_date or date.min, current.session_id)


def _race_group(result: AthleteResult) -> str:
    return (result.race_category or result.race_name).strip().casefold()
