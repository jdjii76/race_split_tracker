"""Pure Coach Analytics catalog and selection helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from split_tracker.repository import Meet, Race, RaceRepository, RaceSession


ANALYTICS_SESSION_STATUSES = {"awaiting_review", "completed"}


@dataclass(frozen=True)
class AnalyticsRaceOption:
    meet: Meet
    race: Race
    session: RaceSession


def load_analytics_catalog(repository: RaceRepository) -> list[AnalyticsRaceOption]:
    """Load lightweight eligible meet/race/session metadata, not race analytics."""
    meets = [meet for meet in repository.list_meets() if meet.status != "archived"]
    meet_by_id = {meet.id: meet for meet in meets}
    races = [race for meet in meets for race in repository.list_races_for_meet(meet.id)
             if race.status != "archived" and not race.name.lstrip().upper().startswith("TEST")]
    race_by_id = {race.id: race for race in races}
    sessions = repository.list_race_sessions_for_races(list(race_by_id)) if race_by_id else []
    eligible = [session for session in sessions if session.status in ANALYTICS_SESSION_STATUSES]
    latest_by_race: dict[str, RaceSession] = {}
    for session in eligible:
        current = latest_by_race.get(session.race_id)
        if current is None or (session.created_at, session.id) > (current.created_at, current.id):
            latest_by_race[session.race_id] = session
    options = [AnalyticsRaceOption(meet_by_id[race.meet_id], race, session)
               for race_id, session in latest_by_race.items()
               if (race := race_by_id.get(race_id)) is not None and race.meet_id in meet_by_id]
    return sorted(options, key=lambda item: (
        item.session.ended_at or item.session.created_at,
        item.meet.meet_date or date.min,
        item.session.id,
    ), reverse=True)


def resolve_analytics_option(
    options: list[AnalyticsRaceOption],
    *,
    saved_meet_id: str | None = None,
    saved_race_id: str | None = None,
    saved_session_id: str | None = None,
    contextual_race_id: str | None = None,
    contextual_session_id: str | None = None,
    active_race_id: str | None = None,
) -> AnalyticsRaceOption | None:
    """Resolve stable IDs using saved, contextual, active, then recent priority."""
    def matching(race_id, session_id=None, meet_id=None):
        return next((item for item in options
                     if item.race.id == race_id
                     and (session_id is None or item.session.id == session_id)
                     and (meet_id is None or item.meet.id == meet_id)), None)

    selected = matching(saved_race_id, saved_session_id, saved_meet_id) if saved_race_id else None
    if selected:
        return selected
    contextual = matching(contextual_race_id, contextual_session_id) if contextual_race_id else None
    if contextual:
        return contextual
    active = matching(active_race_id) if active_race_id else None
    if active:
        return active
    return next((item for item in options if item.session.status == "completed"), options[0] if options else None)


def meet_label(meet: Meet) -> str:
    date_label = meet.meet_date.strftime("%b %d, %Y") if meet.meet_date else "Date TBD"
    return f"{meet.name} — {date_label}"
