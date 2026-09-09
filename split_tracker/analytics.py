"""Pure, read-only post-race analytics derived from finalized result projections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import fmean
from typing import Iterable

from split_tracker.models import Checkpoint
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


@dataclass(frozen=True)
class TeamPosition:
    """KMHS-only ordinal ranks for one athlete in one canonical result projection."""

    result: AthleteResult
    checkpoint_ranks: tuple[int | None, ...]
    finish_rank: int | None
    net_change: int | None


def _athlete_order(result: AthleteResult) -> tuple[str, str, str]:
    parts = result.athlete_name.strip().split()
    return ((parts[-1] if parts else "").casefold(),
            (" ".join(parts[:-1]) if len(parts) > 1 else result.athlete_name).casefold(),
            result.athlete_id)


def _valid_elapsed(result: AthleteResult, checkpoint: Checkpoint) -> float | None:
    split = next((item for item in result.splits
                  if item.get("label") == checkpoint.label
                  and abs(float(item.get("distance_meters", -1)) - checkpoint.distance_meters) < DISTANCE_TOLERANCE_METERS), None)
    if split is None:
        return None
    value = split.get("cumulative")
    return float(value) if value is not None and float(value) > 0 else None


def compute_team_checkpoint_ranks(
    results: Iterable[AthleteResult], checkpoints: Iterable[Checkpoint]
) -> dict[str, tuple[int | None, ...]]:
    """Rank valid canonical splits using stable ordinal KMHS-only ordering."""
    rows, checkpoints = list(results), list(checkpoints)
    ranks = {row.athlete_id: [None] * len(checkpoints) for row in rows}
    for index, checkpoint in enumerate(checkpoints):
        if checkpoint.is_finish:
            continue
        eligible = [(elapsed, row) for row in rows if (elapsed := _valid_elapsed(row, checkpoint)) is not None]
        eligible.sort(key=lambda item: (item[0], *_athlete_order(item[1])))
        for rank, (_, row) in enumerate(eligible, 1):
            ranks[row.athlete_id][index] = rank
    return {athlete_id: tuple(values) for athlete_id, values in ranks.items()}


def compute_team_position_change(
    results: Iterable[AthleteResult], checkpoints: Iterable[Checkpoint]
) -> list[TeamPosition]:
    """Build checkpoint, finish, and net KMHS position changes from canonical results."""
    rows, checkpoints = list(results), list(checkpoints)
    checkpoint_ranks = compute_team_checkpoint_ranks(rows, checkpoints)
    finishers = sorted((row for row in rows if row.status == "Finished" and row.finish_seconds is not None
                        and row.finish_seconds > 0), key=lambda row: (row.finish_seconds, *_athlete_order(row)))
    finish_ranks = {row.athlete_id: rank for rank, row in enumerate(finishers, 1)}
    positions = []
    for row in rows:
        ranks = checkpoint_ranks[row.athlete_id]
        finish_rank = finish_ranks.get(row.athlete_id)
        earliest = next((rank for rank in ranks if rank is not None), None)
        change = earliest - finish_rank if earliest is not None and finish_rank is not None else None
        positions.append(TeamPosition(row, ranks, finish_rank, change))
    return sorted(positions, key=lambda item: (
        item.finish_rank is None,
        item.finish_rank if item.finish_rank is not None else next((rank for rank in reversed(item.checkpoint_ranks) if rank is not None), 10**9),
        *_athlete_order(item.result),
    ))


def build_team_position_insights(positions: Iterable[TeamPosition], checkpoints: Iterable[Checkpoint]) -> list[str]:
    """Describe supported KMHS-relative movements; omit claims without enough data."""
    rows, checkpoints = list(positions), list(checkpoints)
    messages: list[str] = []
    positive_rows = sorted((row for row in rows if row.net_change is not None and row.net_change > 0),
                           key=lambda row: (-row.net_change, _athlete_order(row.result)))
    positive = positive_rows[0] if positive_rows else None
    negative = min((row for row in rows if row.net_change is not None and row.net_change < 0),
                   key=lambda row: (row.net_change, _athlete_order(row.result)), default=None)
    if positive:
        start = positive.finish_rank + positive.net_change
        messages.append(f"Biggest mover: {positive.result.athlete_name} moved from {start} to {positive.finish_rank} among KMHS runners (+{positive.net_change}).")
    if negative:
        start = negative.finish_rank + negative.net_change
        messages.append(f"Largest drop: {negative.result.athlete_name} moved from {start} to {negative.finish_rank} among KMHS runners ({negative.net_change}).")
    final_checkpoint = next((index for index in range(len(checkpoints)-1, -1, -1)
                             if not checkpoints[index].is_finish), None)
    late = ([(row.checkpoint_ranks[final_checkpoint], row) for row in rows
             if row.checkpoint_ranks[final_checkpoint] is not None and row.finish_rank is not None]
            if final_checkpoint is not None else [])
    late_moves = [(prior-row.finish_rank, prior, row) for prior, row in late if prior-row.finish_rank > 0]
    if late_moves:
        gain, prior, row = sorted(late_moves, key=lambda item: (-item[0], _athlete_order(item[2].result)))[0]
        messages.append(f"Strongest late move: {row.result.athlete_name} moved from {prior} to {row.finish_rank} among KMHS runners between {checkpoints[final_checkpoint].label} and Finish (+{gain}).")
    stable = []
    for row in rows:
        values = [rank for rank in (*row.checkpoint_ranks, row.finish_rank) if rank is not None]
        if len(values) >= 2:
            stable.append((max(values)-min(values), row))
    if stable:
        spread, row = min(stable, key=lambda item: (item[0], _athlete_order(item[1].result)))
        messages.append(f"Most stable: {row.result.athlete_name}'s KMHS rank varied by {spread} position{'s' if spread != 1 else ''}.")
    return messages


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
