"""Pure selection helpers for the standalone race-day timer workflow."""
from __future__ import annotations

from dataclasses import dataclass

from split_tracker.calculations import generate_checkpoints
from split_tracker.models import Checkpoint
from split_tracker.repository import Meet, Race, RaceSession
from split_tracker.session_checkpoints import snapshots_to_checkpoints


@dataclass(frozen=True)
class TimerRaceOption:
    meet: Meet
    race: Race
    session: RaceSession | None
    checkpoints: tuple[Checkpoint, ...]

    @property
    def status_label(self) -> str:
        status = self.session.status if self.session else self.race.status
        return {"ready": "Ready", "running": "Running", "paused": "Paused"}.get(status, status.title())


def race_is_available(race: Race, session: RaceSession | None) -> bool:
    """Return whether a race is relevant to an on-duty timer."""
    status = session.status if session else race.status
    return status in {"ready", "running", "paused"}


def configured_checkpoints(race: Race) -> tuple[Checkpoint, ...]:
    return tuple(generate_checkpoints(
        race_distance_meters=race.distance_meters,
        mode=race.checkpoint_mode or "Standard laps",
        interval_meters=400.0 if race.course_type == "Track" else 1609.344,
    ))


def build_timer_options(repository) -> list[TimerRaceOption]:
    """Load timer-ready races without exposing setup or reporting concepts."""
    options: list[TimerRaceOption] = []
    for meet in repository.list_meets():
        if meet.status not in {"draft", "active", "upcoming"}:
            continue
        races = [race for race in repository.list_races_for_meet(meet.id) if race.status != "archived"]
        sessions = repository.list_race_sessions_for_races([race.id for race in races]) if races else []
        by_race: dict[str, list[RaceSession]] = {}
        for session in sessions:
            by_race.setdefault(session.race_id, []).append(session)
        for race in races:
            race_sessions = sorted(
                by_race.get(race.id, []), key=lambda item: (item.created_at, item.id)
            )
            relevant = [
                item
                for item in race_sessions
                if item.status in {"ready", "running", "paused"}
            ]
            session = (relevant or race_sessions)[-1] if race_sessions else None
            if not race_is_available(race, session):
                continue
            checkpoints = configured_checkpoints(race)
            if session is not None:
                snapshots = repository.list_race_session_checkpoints(session.id)
                if snapshots:
                    checkpoints = tuple(snapshots_to_checkpoints(snapshots))
            options.append(TimerRaceOption(meet, race, session, checkpoints))
    return options
