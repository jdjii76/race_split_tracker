"""Repository abstractions for Phase 1 meet and race persistence."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from split_tracker.config import load_supabase_config
from split_tracker.models import Athlete, Checkpoint
from split_tracker.supabase_client import SupabaseConnectionResult, create_supabase_connection

MEET_STATUSES = {"draft", "active", "upcoming", "completed", "archived"}
RACE_STATUSES = {"draft", "ready", "running", "paused", "completed", "archived"}
RACE_SESSION_STATUSES = {"ready", "running", "paused", "completed", "cancelled"}
TEMPLATE_STATUSES = {"active", "archived"}
DEFAULT_XC_TEMPLATE_NAME = "Default XC Meet"
DEFAULT_XC_RACES = ["Boys JV", "Girls JV", "Boys Varsity", "Girls Varsity"]
DELETE_ALL_FILTER_SENTINEL = "00000000-0000-0000-0000-000000000000"

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Meet:
    name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    meet_date: date | None = None
    location: str = ""
    season: str = ""
    notes: str = ""
    status: str = "draft"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class Race:
    meet_id: str
    name: str
    distance_meters: float
    id: str = field(default_factory=lambda: str(uuid4()))
    race_category: str = ""
    scheduled_start: datetime | None = None
    course_type: str = "Cross Country"
    checkpoint_mode: str = "Standard laps"
    status: str = "draft"
    display_order: int = 0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class MeetTemplate:
    name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    season: str = ""
    status: str = "active"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class TemplateRace:
    template_id: str
    name: str
    distance_meters: float
    id: str = field(default_factory=lambda: str(uuid4()))
    race_category: str = ""
    course_type: str = "Cross Country"
    checkpoint_mode: str = "Standard laps"
    display_order: int = 0
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class RaceSession:
    race_id: str
    status: str = "ready"
    id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime | None = None
    paused_at: datetime | None = None
    ended_at: datetime | None = None
    elapsed_offset_seconds: float = 0.0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class SplitEvent:
    race_session_id: str
    athlete_id: str
    checkpoint_number: int
    elapsed_seconds: float
    event_order: int
    id: str = field(default_factory=lambda: str(uuid4()))
    athlete_name: str = ""
    bib_number: str = ""
    checkpoint_label: str = ""
    is_deleted: bool = False
    recorded_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class RaceSessionCheckpoint:
    race_session_id: str
    checkpoint_sequence: int
    label: str
    distance_meters: float
    id: str = field(default_factory=lambda: str(uuid4()))
    distance_unit: str = "meters"
    lap_number: int | None = None
    checkpoint_type: str = "split"
    source_checkpoint_id: str = ""
    is_finish: bool = False
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class RepositoryFactoryResult:
    repository: "RaceRepository | None"
    storage_label: str
    is_temporary: bool
    message: str
    error: str | None = None


class RepositoryError(RuntimeError):
    """Raised when a repository operation cannot be completed."""


class RaceRepository(Protocol):
    """Persistence contract for meet, race, and template management."""

    def create_meet(self, meet: Meet) -> Meet: ...
    def update_meet(self, meet: Meet) -> Meet: ...
    def get_meet(self, meet_id: str) -> Meet | None: ...
    def list_meets(self, *, season: str | None = None, include_archived: bool = False) -> list[Meet]: ...
    def archive_meet(self, meet_id: str) -> Meet: ...
    def delete_draft_meet(self, meet_id: str) -> bool: ...
    def delete_meet(self, meet_id: str) -> bool: ...
    def create_race(self, race: Race) -> Race: ...
    def update_race(self, race: Race) -> Race: ...
    def get_race(self, race_id: str) -> Race | None: ...
    def list_races_for_meet(self, meet_id: str) -> list[Race]: ...
    def duplicate_race(self, race_id: str) -> Race: ...
    def archive_race(self, race_id: str) -> Race: ...
    def delete_draft_race(self, race_id: str) -> bool: ...
    def delete_race(self, race_id: str) -> bool: ...
    def list_race_athletes(self, race_id: str, *, include_inactive: bool = False) -> list[Athlete]: ...
    def replace_race_athletes(self, race_id: str, athletes: list[Athlete]) -> list[Athlete]: ...
    def delete_race_athlete(self, race_id: str, athlete_id: str) -> bool: ...
    def clear_race_roster(self, race_id: str) -> bool: ...
    def create_template(self, template: MeetTemplate, races: list[TemplateRace] | None = None) -> MeetTemplate: ...
    def update_template(self, template: MeetTemplate) -> MeetTemplate: ...
    def get_template(self, template_id: str) -> MeetTemplate | None: ...
    def list_templates(self, *, include_archived: bool = False) -> list[MeetTemplate]: ...
    def list_template_races(self, template_id: str) -> list[TemplateRace]: ...
    def apply_template_to_meet(self, template_id: str, meet: Meet) -> tuple[Meet, list[Race]]: ...
    def archive_template(self, template_id: str) -> MeetTemplate: ...
    def seed_default_xc_template(self) -> MeetTemplate: ...

    def create_race_session(self, session: RaceSession) -> RaceSession: ...
    def create_started_race_session_with_checkpoints(self, session: RaceSession, checkpoints: list[Checkpoint]) -> RaceSession: ...
    def get_race_session(self, race_session_id: str) -> RaceSession | None: ...
    def get_active_or_latest_race_session_for_race(self, race_id: str) -> RaceSession | None: ...
    def update_race_session(self, session: RaceSession) -> RaceSession: ...
    def list_race_sessions_for_race(self, race_id: str) -> list[RaceSession]: ...
    def create_split_event(self, event: SplitEvent) -> SplitEvent: ...
    def list_active_split_events(self, race_session_id: str) -> list[SplitEvent]: ...
    def list_all_split_events(self, race_session_id: str) -> list[SplitEvent]: ...
    def soft_delete_split_event(self, split_event_id: str) -> SplitEvent: ...
    def restore_split_event(self, split_event_id: str) -> SplitEvent: ...
    def delete_race_session(self, race_session_id: str) -> bool: ...
    def delete_all_timing_data(self) -> bool: ...
    def delete_all_race_rosters(self) -> bool: ...
    def delete_all_application_test_data(self) -> bool: ...
    def create_race_session_checkpoints(self, race_session_id: str, checkpoints: list[Checkpoint]) -> list[RaceSessionCheckpoint]: ...
    def list_race_session_checkpoints(self, race_session_id: str) -> list[RaceSessionCheckpoint]: ...


class InMemoryRaceRepository:
    """In-session repository used when Supabase configuration is missing."""

    def __init__(self) -> None:
        self.meets: dict[str, Meet] = {}
        self.races: dict[str, Race] = {}
        self.templates: dict[str, MeetTemplate] = {}
        self.template_races: dict[str, TemplateRace] = {}
        self.race_sessions: dict[str, RaceSession] = {}
        self.split_events: dict[str, SplitEvent] = {}
        self.race_session_checkpoints: dict[tuple[str, int], RaceSessionCheckpoint] = {}
        self.race_athletes: dict[tuple[str, str], Athlete] = {}

    def create_meet(self, meet: Meet) -> Meet:
        saved = replace(meet, created_at=meet.created_at, updated_at=utc_now())
        self.meets[saved.id] = saved
        return saved

    def update_meet(self, meet: Meet) -> Meet:
        if meet.id not in self.meets:
            raise RepositoryError("Meet not found.")
        saved = replace(meet, updated_at=utc_now())
        self.meets[saved.id] = saved
        return saved

    def get_meet(self, meet_id: str) -> Meet | None:
        return self.meets.get(meet_id)

    def list_meets(self, *, season: str | None = None, include_archived: bool = False) -> list[Meet]:
        meets = list(self.meets.values())
        if season:
            meets = [meet for meet in meets if meet.season == season]
        if not include_archived:
            meets = [meet for meet in meets if meet.status != "archived"]
        return sorted(meets, key=lambda meet: (meet.meet_date or date.max, meet.name))

    def archive_meet(self, meet_id: str) -> Meet:
        meet = self._require_meet(meet_id)
        return self.update_meet(replace(meet, status="archived"))

    def delete_draft_meet(self, meet_id: str) -> bool:
        meet = self._require_meet(meet_id)
        if meet.status != "draft":
            return False
        return self.delete_meet(meet_id)

    def delete_meet(self, meet_id: str) -> bool:
        if meet_id not in self.meets:
            return False
        for race in list(self.races.values()):
            if race.meet_id == meet_id:
                self.delete_race(race.id)
        self.meets.pop(meet_id)
        return True

    def create_race(self, race: Race) -> Race:
        self._require_meet(race.meet_id)
        saved = replace(race, created_at=race.created_at, updated_at=utc_now())
        self.races[saved.id] = saved
        return saved

    def update_race(self, race: Race) -> Race:
        if race.id not in self.races:
            raise RepositoryError("Race not found.")
        saved = replace(race, updated_at=utc_now())
        self.races[saved.id] = saved
        return saved

    def get_race(self, race_id: str) -> Race | None:
        return self.races.get(race_id)

    def list_races_for_meet(self, meet_id: str) -> list[Race]:
        return sorted([race for race in self.races.values() if race.meet_id == meet_id], key=lambda race: (race.display_order, race.name))

    def duplicate_race(self, race_id: str) -> Race:
        race = self._require_race(race_id)
        next_order = max([item.display_order for item in self.list_races_for_meet(race.meet_id)] or [0]) + 1
        duplicate = replace(race, id=str(uuid4()), name=f"{race.name} Copy", status="draft", display_order=next_order, created_at=utc_now(), updated_at=utc_now())
        self.races[duplicate.id] = duplicate
        return duplicate

    def archive_race(self, race_id: str) -> Race:
        race = self._require_race(race_id)
        return self.update_race(replace(race, status="archived"))

    def delete_draft_race(self, race_id: str) -> bool:
        race = self._require_race(race_id)
        if race.status != "draft":
            return False
        return self.delete_race(race_id)

    def delete_race(self, race_id: str) -> bool:
        if race_id not in self.races:
            return False
        for key in [key for key in self.race_athletes if key[0] == race_id]:
            self.race_athletes.pop(key)
        for session in [session for session in self.race_sessions.values() if session.race_id == race_id]:
            self.delete_race_session(session.id)
        self.races.pop(race_id)
        return True

    def list_race_athletes(self, race_id: str, *, include_inactive: bool = False) -> list[Athlete]:
        self._require_race(race_id)
        athletes = [athlete for (stored_race_id, _), athlete in self.race_athletes.items() if stored_race_id == race_id]
        if not include_inactive:
            athletes = [athlete for athlete in athletes if athlete.active]
        return sorted(athletes, key=lambda athlete: (athlete.display_order, athlete.name, athlete.athlete_id))

    def replace_race_athletes(self, race_id: str, athletes: list[Athlete]) -> list[Athlete]:
        self._require_race(race_id)
        for key in [key for key in self.race_athletes if key[0] == race_id]:
            self.race_athletes.pop(key)
        saved = [replace(athlete, display_order=index) for index, athlete in enumerate(athletes)]
        for athlete in saved:
            self.race_athletes[(race_id, athlete.athlete_id)] = athlete
        return self.list_race_athletes(race_id, include_inactive=True)

    def delete_race_athlete(self, race_id: str, athlete_id: str) -> bool:
        self._require_race(race_id)
        return self.race_athletes.pop((race_id, athlete_id), None) is not None

    def clear_race_roster(self, race_id: str) -> bool:
        self._require_race(race_id)
        keys = [key for key in self.race_athletes if key[0] == race_id]
        for key in keys:
            self.race_athletes.pop(key)
        return bool(keys)

    def create_template(self, template: MeetTemplate, races: list[TemplateRace] | None = None) -> MeetTemplate:
        saved = replace(template, created_at=template.created_at, updated_at=utc_now())
        self.templates[saved.id] = saved
        for race in races or []:
            self.template_races[race.id] = replace(race, template_id=saved.id)
        return saved

    def update_template(self, template: MeetTemplate) -> MeetTemplate:
        if template.id not in self.templates:
            raise RepositoryError("Template not found.")
        saved = replace(template, updated_at=utc_now())
        self.templates[saved.id] = saved
        return saved

    def get_template(self, template_id: str) -> MeetTemplate | None:
        return self.templates.get(template_id)

    def list_templates(self, *, include_archived: bool = False) -> list[MeetTemplate]:
        templates = list(self.templates.values())
        if not include_archived:
            templates = [template for template in templates if template.status != "archived"]
        return sorted(templates, key=lambda template: template.name)

    def list_template_races(self, template_id: str) -> list[TemplateRace]:
        return sorted([race for race in self.template_races.values() if race.template_id == template_id], key=lambda race: (race.display_order, race.name))

    def apply_template_to_meet(self, template_id: str, meet: Meet) -> tuple[Meet, list[Race]]:
        self._require_template(template_id)
        saved_meet = self.create_meet(meet)
        races = [
            self.create_race(
                Race(
                    meet_id=saved_meet.id,
                    name=template_race.name,
                    race_category=template_race.race_category,
                    distance_meters=template_race.distance_meters,
                    course_type=template_race.course_type,
                    checkpoint_mode=template_race.checkpoint_mode,
                    display_order=template_race.display_order,
                )
            )
            for template_race in self.list_template_races(template_id)
        ]
        return saved_meet, races

    def archive_template(self, template_id: str) -> MeetTemplate:
        template = self._require_template(template_id)
        return self.update_template(replace(template, status="archived"))

    def seed_default_xc_template(self) -> MeetTemplate:
        for template in self.templates.values():
            if template.name == DEFAULT_XC_TEMPLATE_NAME:
                return template
        template = MeetTemplate(name=DEFAULT_XC_TEMPLATE_NAME, description="Standard four-race cross country meet", season="Cross Country")
        races = [
            TemplateRace(template_id=template.id, name=name, distance_meters=5000.0, course_type="Cross Country", checkpoint_mode="Standard laps", display_order=index)
            for index, name in enumerate(DEFAULT_XC_RACES)
        ]
        return self.create_template(template, races)


    def create_race_session(self, session: RaceSession) -> RaceSession:
        self._require_race(session.race_id)
        saved = replace(session, created_at=session.created_at, updated_at=utc_now())
        self.race_sessions[saved.id] = saved
        return saved

    def create_started_race_session_with_checkpoints(self, session: RaceSession, checkpoints: list[Checkpoint]) -> RaceSession:
        if not checkpoints:
            raise RepositoryError("At least one checkpoint is required to start a race session.")
        draft = replace(session, status="ready")
        saved = self.create_race_session(draft)
        try:
            self.create_race_session_checkpoints(saved.id, checkpoints)
            started = self.update_race_session(replace(saved, status=session.status, started_at=session.started_at, elapsed_offset_seconds=session.elapsed_offset_seconds))
            return started
        except Exception:
            self.delete_race_session(saved.id)
            raise

    def get_race_session(self, race_session_id: str) -> RaceSession | None:
        return self.race_sessions.get(race_session_id)

    def get_active_or_latest_race_session_for_race(self, race_id: str) -> RaceSession | None:
        sessions = self.list_race_sessions_for_race(race_id)
        active = [session for session in sessions if session.status in {"running", "paused"}]
        if active:
            return active[-1]
        return sessions[-1] if sessions else None

    def update_race_session(self, session: RaceSession) -> RaceSession:
        if session.id not in self.race_sessions:
            raise RepositoryError("Race session not found.")
        saved = replace(session, updated_at=utc_now())
        self.race_sessions[saved.id] = saved
        return saved

    def list_race_sessions_for_race(self, race_id: str) -> list[RaceSession]:
        return sorted([session for session in self.race_sessions.values() if session.race_id == race_id], key=lambda session: (session.created_at, session.id))

    def create_split_event(self, event: SplitEvent) -> SplitEvent:
        if event.race_session_id not in self.race_sessions:
            raise RepositoryError("Race session not found.")
        saved = replace(event, created_at=event.created_at, updated_at=utc_now())
        self.split_events[saved.id] = saved
        return saved

    def list_active_split_events(self, race_session_id: str) -> list[SplitEvent]:
        return [event for event in self.list_all_split_events(race_session_id) if not event.is_deleted]

    def list_all_split_events(self, race_session_id: str) -> list[SplitEvent]:
        return sorted([event for event in self.split_events.values() if event.race_session_id == race_session_id], key=lambda event: (event.event_order, event.recorded_at, event.id))

    def soft_delete_split_event(self, split_event_id: str) -> SplitEvent:
        event = self._require_split_event(split_event_id)
        saved = replace(event, is_deleted=True, updated_at=utc_now())
        self.split_events[saved.id] = saved
        return saved

    def restore_split_event(self, split_event_id: str) -> SplitEvent:
        event = self._require_split_event(split_event_id)
        saved = replace(event, is_deleted=False, updated_at=utc_now())
        self.split_events[saved.id] = saved
        return saved

    def create_race_session_checkpoints(self, race_session_id: str, checkpoints: list[Checkpoint]) -> list[RaceSessionCheckpoint]:
        if race_session_id not in self.race_sessions:
            raise RepositoryError("Race session not found.")
        existing = self.list_race_session_checkpoints(race_session_id)
        if existing:
            return existing
        seen: set[int] = set()
        snapshots: list[RaceSessionCheckpoint] = []
        for checkpoint in checkpoints:
            if checkpoint.number in seen:
                raise RepositoryError("Duplicate checkpoint sequence for race session.")
            seen.add(checkpoint.number)
            snapshot = RaceSessionCheckpoint(
                race_session_id=race_session_id,
                checkpoint_sequence=checkpoint.number,
                label=checkpoint.label,
                distance_meters=checkpoint.distance_meters,
                checkpoint_type="finish" if checkpoint.is_finish else _checkpoint_type_from_label(checkpoint.label),
                is_finish=checkpoint.is_finish,
            )
            snapshots.append(snapshot)
        for snapshot in snapshots:
            self.race_session_checkpoints[(race_session_id, snapshot.checkpoint_sequence)] = snapshot
        return self.list_race_session_checkpoints(race_session_id)

    def list_race_session_checkpoints(self, race_session_id: str) -> list[RaceSessionCheckpoint]:
        return sorted(
            [checkpoint for (session_id, _), checkpoint in self.race_session_checkpoints.items() if session_id == race_session_id],
            key=lambda checkpoint: (checkpoint.checkpoint_sequence, checkpoint.id),
        )

    def delete_race_session(self, race_session_id: str) -> bool:
        if race_session_id not in self.race_sessions:
            return False
        for event_id in [event.id for event in self.split_events.values() if event.race_session_id == race_session_id]:
            self.split_events.pop(event_id)
        for key in [key for key in self.race_session_checkpoints if key[0] == race_session_id]:
            self.race_session_checkpoints.pop(key)
        self.race_sessions.pop(race_session_id)
        return True

    def delete_all_timing_data(self) -> bool:
        had_data = bool(self.race_sessions or self.split_events or self.race_session_checkpoints)
        self.split_events.clear()
        self.race_session_checkpoints.clear()
        self.race_sessions.clear()
        return had_data

    def delete_all_race_rosters(self) -> bool:
        had_data = bool(self.race_athletes)
        self.race_athletes.clear()
        return had_data

    def delete_all_application_test_data(self) -> bool:
        had_data = bool(self.meets or self.races or self.race_athletes or self.race_sessions or self.split_events or self.race_session_checkpoints)
        self.split_events.clear()
        self.race_session_checkpoints.clear()
        self.race_sessions.clear()
        self.race_athletes.clear()
        self.races.clear()
        self.meets.clear()
        return had_data

    def _require_meet(self, meet_id: str) -> Meet:
        meet = self.get_meet(meet_id)
        if meet is None:
            raise RepositoryError("Meet not found.")
        return meet

    def _require_race(self, race_id: str) -> Race:
        race = self.get_race(race_id)
        if race is None:
            raise RepositoryError("Race not found.")
        return race

    def _require_template(self, template_id: str) -> MeetTemplate:
        template = self.get_template(template_id)
        if template is None:
            raise RepositoryError("Template not found.")
        return template

    def _require_split_event(self, split_event_id: str) -> SplitEvent:
        event = self.split_events.get(split_event_id)
        if event is None:
            raise RepositoryError("Split event not found.")
        return event


def _to_iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _meet_to_row(meet: Meet) -> dict[str, Any]:
    return {
        "id": meet.id,
        "name": meet.name,
        "meet_date": _to_iso(meet.meet_date),
        "location": meet.location or None,
        "season": meet.season or None,
        "notes": meet.notes or None,
        "status": meet.status,
        "created_at": meet.created_at.isoformat(),
        "updated_at": meet.updated_at.isoformat(),
    }


def _meet_from_row(row: dict[str, Any]) -> Meet:
    return Meet(
        id=str(row["id"]),
        name=str(row["name"]),
        meet_date=_parse_date(row.get("meet_date")),
        location=row.get("location") or "",
        season=row.get("season") or "",
        notes=row.get("notes") or "",
        status=row.get("status") or "draft",
        created_at=_parse_datetime(row.get("created_at")) or utc_now(),
        updated_at=_parse_datetime(row.get("updated_at")) or utc_now(),
    )


def _race_to_row(race: Race) -> dict[str, Any]:
    return {
        "id": race.id,
        "meet_id": race.meet_id,
        "name": race.name,
        "race_category": race.race_category or None,
        "scheduled_start": _to_iso(race.scheduled_start),
        "course_type": race.course_type or None,
        "distance_meters": race.distance_meters,
        "checkpoint_mode": race.checkpoint_mode or None,
        "status": race.status,
        "display_order": race.display_order,
        "created_at": race.created_at.isoformat(),
        "updated_at": race.updated_at.isoformat(),
    }


def _race_from_row(row: dict[str, Any]) -> Race:
    return Race(
        id=str(row["id"]),
        meet_id=str(row["meet_id"]),
        name=str(row["name"]),
        race_category=row.get("race_category") or "",
        scheduled_start=_parse_datetime(row.get("scheduled_start")),
        course_type=row.get("course_type") or "Cross Country",
        distance_meters=float(row["distance_meters"]),
        checkpoint_mode=row.get("checkpoint_mode") or "Standard laps",
        status=row.get("status") or "draft",
        display_order=int(row.get("display_order") or 0),
        created_at=_parse_datetime(row.get("created_at")) or utc_now(),
        updated_at=_parse_datetime(row.get("updated_at")) or utc_now(),
    )


def _template_to_row(template: MeetTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description or None,
        "season": template.season or None,
        "status": template.status,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def _template_from_row(row: dict[str, Any]) -> MeetTemplate:
    return MeetTemplate(
        id=str(row["id"]),
        name=str(row["name"]),
        description=row.get("description") or "",
        season=row.get("season") or "",
        status=row.get("status") or "active",
        created_at=_parse_datetime(row.get("created_at")) or utc_now(),
        updated_at=_parse_datetime(row.get("updated_at")) or utc_now(),
    )


def _template_race_to_row(race: TemplateRace) -> dict[str, Any]:
    return {
        "id": race.id,
        "template_id": race.template_id,
        "name": race.name,
        "race_category": race.race_category or None,
        "distance_meters": race.distance_meters,
        "course_type": race.course_type or None,
        "checkpoint_mode": race.checkpoint_mode or None,
        "display_order": race.display_order,
        "created_at": race.created_at.isoformat(),
    }


def _template_race_from_row(row: dict[str, Any]) -> TemplateRace:
    return TemplateRace(
        id=str(row["id"]),
        template_id=str(row["template_id"]),
        name=str(row["name"]),
        race_category=row.get("race_category") or "",
        distance_meters=float(row["distance_meters"]),
        course_type=row.get("course_type") or "Cross Country",
        checkpoint_mode=row.get("checkpoint_mode") or "Standard laps",
        display_order=int(row.get("display_order") or 0),
        created_at=_parse_datetime(row.get("created_at")) or utc_now(),
    )


def _race_session_to_row(session: RaceSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "race_id": session.race_id,
        "status": session.status,
        "started_at": _to_iso(session.started_at),
        "paused_at": _to_iso(session.paused_at),
        "ended_at": _to_iso(session.ended_at),
        "elapsed_offset_seconds": session.elapsed_offset_seconds,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


def _race_session_from_row(row: dict[str, Any]) -> RaceSession:
    return RaceSession(
        id=str(row["id"]),
        race_id=str(row["race_id"]),
        status=row.get("status") or "ready",
        started_at=_parse_datetime(row.get("started_at")),
        paused_at=_parse_datetime(row.get("paused_at")),
        ended_at=_parse_datetime(row.get("ended_at")),
        elapsed_offset_seconds=float(row.get("elapsed_offset_seconds") or 0.0),
        created_at=_parse_datetime(row.get("created_at")) or utc_now(),
        updated_at=_parse_datetime(row.get("updated_at")) or utc_now(),
    )


def _split_event_to_row(event: SplitEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "race_session_id": event.race_session_id,
        "athlete_id": event.athlete_id,
        "athlete_name": event.athlete_name or None,
        "bib_number": event.bib_number or None,
        "checkpoint_number": event.checkpoint_number,
        "checkpoint_label": event.checkpoint_label or None,
        "elapsed_seconds": event.elapsed_seconds,
        "recorded_at": event.recorded_at.isoformat(),
        "event_order": event.event_order,
        "is_deleted": event.is_deleted,
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat(),
    }


def _split_event_from_row(row: dict[str, Any]) -> SplitEvent:
    return SplitEvent(
        id=str(row["id"]),
        race_session_id=str(row["race_session_id"]),
        athlete_id=str(row["athlete_id"]),
        athlete_name=row.get("athlete_name") or "",
        bib_number=row.get("bib_number") or "",
        checkpoint_number=int(row["checkpoint_number"]),
        checkpoint_label=row.get("checkpoint_label") or "",
        elapsed_seconds=float(row["elapsed_seconds"]),
        recorded_at=_parse_datetime(row.get("recorded_at")) or utc_now(),
        event_order=int(row.get("event_order") or 0),
        is_deleted=bool(row.get("is_deleted")),
        created_at=_parse_datetime(row.get("created_at")) or utc_now(),
        updated_at=_parse_datetime(row.get("updated_at")) or utc_now(),
    )


def _checkpoint_type_from_label(label: str) -> str:
    lowered = label.lower()
    if lowered == "finish":
        return "finish"
    if "mile" in lowered:
        return "mile"
    if lowered.endswith("k"):
        return "kilometer"
    if "lap" in lowered:
        return "lap"
    return "split"


def _session_checkpoint_to_row(snapshot: RaceSessionCheckpoint) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "race_session_id": snapshot.race_session_id,
        "checkpoint_sequence": snapshot.checkpoint_sequence,
        "label": snapshot.label,
        "distance_meters": snapshot.distance_meters,
        "distance_unit": snapshot.distance_unit,
        "lap_number": snapshot.lap_number,
        "checkpoint_type": snapshot.checkpoint_type,
        "source_checkpoint_id": snapshot.source_checkpoint_id or None,
        "is_finish": snapshot.is_finish,
        "created_at": snapshot.created_at.isoformat(),
    }


def _session_checkpoint_from_row(row: dict[str, Any]) -> RaceSessionCheckpoint:
    return RaceSessionCheckpoint(
        id=str(row["id"]),
        race_session_id=str(row["race_session_id"]),
        checkpoint_sequence=int(row["checkpoint_sequence"]),
        label=str(row["label"]),
        distance_meters=float(row["distance_meters"]),
        distance_unit=row.get("distance_unit") or "meters",
        lap_number=int(row["lap_number"]) if row.get("lap_number") is not None else None,
        checkpoint_type=row.get("checkpoint_type") or "split",
        source_checkpoint_id=row.get("source_checkpoint_id") or "",
        is_finish=bool(row.get("is_finish")),
        created_at=_parse_datetime(row.get("created_at")) or utc_now(),
    )


def _session_checkpoint_from_checkpoint(race_session_id: str, checkpoint: Checkpoint) -> RaceSessionCheckpoint:
    return RaceSessionCheckpoint(
        race_session_id=race_session_id,
        checkpoint_sequence=checkpoint.number,
        label=checkpoint.label,
        distance_meters=checkpoint.distance_meters,
        checkpoint_type="finish" if checkpoint.is_finish else _checkpoint_type_from_label(checkpoint.label),
        is_finish=checkpoint.is_finish,
    )


def _session_checkpoint_rpc_payload(checkpoint: Checkpoint) -> dict[str, Any]:
    snapshot = _session_checkpoint_from_checkpoint("", checkpoint)
    row = _session_checkpoint_to_row(snapshot)
    return {
        key: value
        for key, value in row.items()
        if key not in {"id", "race_session_id", "created_at"}
    }


def _athlete_to_row(race_id: str, athlete: Athlete, display_order: int | None = None) -> dict[str, Any]:
    return {
        "race_id": race_id,
        "athlete_id": athlete.athlete_id,
        "name": athlete.name,
        "bib_number": athlete.bib_number or None,
        "gender": athlete.gender or None,
        "grade": athlete.grade or None,
        "team": athlete.team or None,
        "target_finish_time_seconds": athlete.target_finish_time_seconds,
        "target_pace_seconds_per_mile": athlete.target_pace_seconds_per_mile,
        "group_category": athlete.group or None,
        "display_order": athlete.display_order if display_order is None else display_order,
        "active": athlete.active,
    }


def _athlete_from_row(row: dict[str, Any]) -> Athlete:
    return Athlete(
        athlete_id=str(row.get("athlete_id") or row["id"]),
        name=str(row["name"]),
        bib_number=row.get("bib_number") or "",
        gender=row.get("gender") or "",
        grade=row.get("grade") or "",
        team=row.get("team") or "",
        target_finish_time_seconds=float(row["target_finish_time_seconds"]) if row.get("target_finish_time_seconds") is not None else None,
        target_pace_seconds_per_mile=float(row["target_pace_seconds_per_mile"]) if row.get("target_pace_seconds_per_mile") is not None else None,
        group=row.get("group_category") or "",
        display_order=int(row.get("display_order") or 0),
        active=bool(row.get("active", True)),
    )


class SupabaseRaceRepository:
    """Supabase-backed repository using the official Python client."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def _execute(self, operation: Any, message: str) -> Any:
        try:
            return operation.execute()
        except Exception as exc:
            logger.exception("Repository operation failed: %s", message)
            raise RepositoryError(message) from exc

    def _single(self, operation: Any, message: str) -> dict[str, Any] | None:
        result = self._execute(operation, message)
        data = getattr(result, "data", None)
        if isinstance(data, list):
            return data[0] if data else None
        return data

    def create_meet(self, meet: Meet) -> Meet:
        row = self._single(self.client.table("meets").insert(_meet_to_row(meet)), "Could not create meet.")
        return _meet_from_row(row or _meet_to_row(meet))

    def update_meet(self, meet: Meet) -> Meet:
        saved = replace(meet, updated_at=utc_now())
        row = self._single(self.client.table("meets").update(_meet_to_row(saved)).eq("id", saved.id), "Could not update meet.")
        return _meet_from_row(row or _meet_to_row(saved))

    def get_meet(self, meet_id: str) -> Meet | None:
        row = self._single(self.client.table("meets").select("*").eq("id", meet_id), "Could not load meet.")
        return _meet_from_row(row) if row else None

    def list_meets(self, *, season: str | None = None, include_archived: bool = False) -> list[Meet]:
        query = self.client.table("meets").select("*")
        if season:
            query = query.eq("season", season)
        if not include_archived:
            query = query.neq("status", "archived")
        result = self._execute(query.order("meet_date", desc=False).order("name", desc=False), "Could not list meets.")
        return [_meet_from_row(row) for row in getattr(result, "data", [])]

    def archive_meet(self, meet_id: str) -> Meet:
        meet = self.get_meet(meet_id)
        if meet is None:
            raise RepositoryError("Meet not found.")
        return self.update_meet(replace(meet, status="archived"))

    def delete_draft_meet(self, meet_id: str) -> bool:
        meet = self.get_meet(meet_id)
        if meet is None or meet.status != "draft":
            return False
        return self.delete_meet(meet_id)

    def delete_meet(self, meet_id: str) -> bool:
        if self.get_meet(meet_id) is None:
            return False
        self._execute(self.client.table("meets").delete().eq("id", meet_id), "Could not delete meet.")
        return True

    def create_race(self, race: Race) -> Race:
        row = self._single(self.client.table("races").insert(_race_to_row(race)), "Could not create race.")
        return _race_from_row(row or _race_to_row(race))

    def update_race(self, race: Race) -> Race:
        saved = replace(race, updated_at=utc_now())
        row = self._single(self.client.table("races").update(_race_to_row(saved)).eq("id", saved.id), "Could not update race.")
        return _race_from_row(row or _race_to_row(saved))

    def get_race(self, race_id: str) -> Race | None:
        row = self._single(self.client.table("races").select("*").eq("id", race_id), "Could not load race.")
        return _race_from_row(row) if row else None

    def list_races_for_meet(self, meet_id: str) -> list[Race]:
        result = self._execute(self.client.table("races").select("*").eq("meet_id", meet_id).order("display_order", desc=False), "Could not list races.")
        return [_race_from_row(row) for row in getattr(result, "data", [])]

    def duplicate_race(self, race_id: str) -> Race:
        race = self.get_race(race_id)
        if race is None:
            raise RepositoryError("Race not found.")
        next_order = max([item.display_order for item in self.list_races_for_meet(race.meet_id)] or [0]) + 1
        return self.create_race(replace(race, id=str(uuid4()), name=f"{race.name} Copy", status="draft", display_order=next_order, created_at=utc_now(), updated_at=utc_now()))

    def archive_race(self, race_id: str) -> Race:
        race = self.get_race(race_id)
        if race is None:
            raise RepositoryError("Race not found.")
        return self.update_race(replace(race, status="archived"))

    def delete_draft_race(self, race_id: str) -> bool:
        race = self.get_race(race_id)
        if race is None or race.status != "draft":
            return False
        return self.delete_race(race_id)

    def delete_race(self, race_id: str) -> bool:
        if self.get_race(race_id) is None:
            return False
        self._execute(self.client.table("races").delete().eq("id", race_id), "Could not delete race.")
        return True

    def list_race_athletes(self, race_id: str, *, include_inactive: bool = False) -> list[Athlete]:
        query = self.client.table("race_athletes").select("*").eq("race_id", race_id)
        if not include_inactive:
            query = query.eq("active", True)
        result = self._execute(query.order("display_order", desc=False).order("name", desc=False), "Could not list race roster.")
        return [_athlete_from_row(row) for row in getattr(result, "data", [])]

    def replace_race_athletes(self, race_id: str, athletes: list[Athlete]) -> list[Athlete]:
        if self.get_race(race_id) is None:
            raise RepositoryError("Race not found.")
        self._execute(self.client.table("race_athletes").delete().eq("race_id", race_id), "Could not clear race roster.")
        for index, athlete in enumerate(athletes):
            self._execute(self.client.table("race_athletes").insert(_athlete_to_row(race_id, athlete, index)), "Could not save race roster.")
        return self.list_race_athletes(race_id, include_inactive=True)

    def delete_race_athlete(self, race_id: str, athlete_id: str) -> bool:
        self._execute(self.client.table("race_athletes").delete().eq("race_id", race_id).eq("athlete_id", athlete_id), "Could not delete roster athlete.")
        return True

    def clear_race_roster(self, race_id: str) -> bool:
        if self.get_race(race_id) is None:
            return False
        had_roster = bool(self.list_race_athletes(race_id, include_inactive=True))
        self._execute(self.client.table("race_athletes").delete().eq("race_id", race_id), "Could not clear race roster.")
        return had_roster

    def create_template(self, template: MeetTemplate, races: list[TemplateRace] | None = None) -> MeetTemplate:
        saved = _template_from_row(self._single(self.client.table("meet_templates").insert(_template_to_row(template)), "Could not create template.") or _template_to_row(template))
        for race in races or []:
            self._execute(self.client.table("template_races").insert(_template_race_to_row(replace(race, template_id=saved.id))), "Could not create template race.")
        return saved

    def update_template(self, template: MeetTemplate) -> MeetTemplate:
        saved = replace(template, updated_at=utc_now())
        row = self._single(self.client.table("meet_templates").update(_template_to_row(saved)).eq("id", saved.id), "Could not update template.")
        return _template_from_row(row or _template_to_row(saved))

    def get_template(self, template_id: str) -> MeetTemplate | None:
        row = self._single(self.client.table("meet_templates").select("*").eq("id", template_id), "Could not load template.")
        return _template_from_row(row) if row else None

    def list_templates(self, *, include_archived: bool = False) -> list[MeetTemplate]:
        query = self.client.table("meet_templates").select("*")
        if not include_archived:
            query = query.neq("status", "archived")
        result = self._execute(query.order("name", desc=False), "Could not list templates.")
        return [_template_from_row(row) for row in getattr(result, "data", [])]

    def list_template_races(self, template_id: str) -> list[TemplateRace]:
        result = self._execute(self.client.table("template_races").select("*").eq("template_id", template_id).order("display_order", desc=False), "Could not list template races.")
        return [_template_race_from_row(row) for row in getattr(result, "data", [])]

    def apply_template_to_meet(self, template_id: str, meet: Meet) -> tuple[Meet, list[Race]]:
        if self.get_template(template_id) is None:
            raise RepositoryError("Template not found.")
        saved_meet = self.create_meet(meet)
        races = [self.create_race(Race(meet_id=saved_meet.id, name=race.name, race_category=race.race_category, distance_meters=race.distance_meters, course_type=race.course_type, checkpoint_mode=race.checkpoint_mode, display_order=race.display_order)) for race in self.list_template_races(template_id)]
        return saved_meet, races

    def archive_template(self, template_id: str) -> MeetTemplate:
        template = self.get_template(template_id)
        if template is None:
            raise RepositoryError("Template not found.")
        return self.update_template(replace(template, status="archived"))

    def seed_default_xc_template(self) -> MeetTemplate:
        for template in self.list_templates(include_archived=True):
            if template.name == DEFAULT_XC_TEMPLATE_NAME:
                return template
        template = MeetTemplate(name=DEFAULT_XC_TEMPLATE_NAME, description="Standard four-race cross country meet", season="Cross Country")
        races = [TemplateRace(template_id=template.id, name=name, distance_meters=5000.0, course_type="Cross Country", checkpoint_mode="Standard laps", display_order=index) for index, name in enumerate(DEFAULT_XC_RACES)]
        return self.create_template(template, races)


    def create_race_session(self, session: RaceSession) -> RaceSession:
        row = self._single(self.client.table("race_sessions").insert(_race_session_to_row(session)), "Could not create race session.")
        return _race_session_from_row(row or _race_session_to_row(session))

    def create_started_race_session_with_checkpoints(self, session: RaceSession, checkpoints: list[Checkpoint]) -> RaceSession:
        if not checkpoints:
            raise RepositoryError("At least one checkpoint is required to start a race session.")
        result = self._execute(
            self.client.rpc(
                "create_started_race_session_with_checkpoints",
                {
                    "p_session_id": session.id,
                    "p_race_id": session.race_id,
                    "p_started_at": _to_iso(session.started_at),
                    "p_elapsed_offset_seconds": session.elapsed_offset_seconds,
                    "p_checkpoints": [_session_checkpoint_rpc_payload(checkpoint) for checkpoint in checkpoints],
                },
            ),
            "Could not create started race session with checkpoint snapshot.",
        )
        data = getattr(result, "data", [])
        if not data:
            raise RepositoryError("Could not create started race session with checkpoint snapshot.")
        return _race_session_from_row(data[0])

    def get_race_session(self, race_session_id: str) -> RaceSession | None:
        row = self._single(self.client.table("race_sessions").select("*").eq("id", race_session_id), "Could not load race session.")
        return _race_session_from_row(row) if row else None

    def get_active_or_latest_race_session_for_race(self, race_id: str) -> RaceSession | None:
        active_result = self._execute(self.client.table("race_sessions").select("*").eq("race_id", race_id).in_("status", ["running", "paused"]).order("created_at", desc=False), "Could not load active race session.")
        active_rows = getattr(active_result, "data", [])
        if active_rows:
            return _race_session_from_row(active_rows[-1])
        all_sessions = self.list_race_sessions_for_race(race_id)
        return all_sessions[-1] if all_sessions else None

    def update_race_session(self, session: RaceSession) -> RaceSession:
        saved = replace(session, updated_at=utc_now())
        row = self._single(self.client.table("race_sessions").update(_race_session_to_row(saved)).eq("id", saved.id), "Could not update race session.")
        return _race_session_from_row(row or _race_session_to_row(saved))

    def list_race_sessions_for_race(self, race_id: str) -> list[RaceSession]:
        result = self._execute(self.client.table("race_sessions").select("*").eq("race_id", race_id).order("created_at", desc=False), "Could not list race sessions.")
        return [_race_session_from_row(row) for row in getattr(result, "data", [])]

    def create_split_event(self, event: SplitEvent) -> SplitEvent:
        row = self._single(self.client.table("split_events").insert(_split_event_to_row(event)), "Could not create split event.")
        return _split_event_from_row(row or _split_event_to_row(event))

    def list_active_split_events(self, race_session_id: str) -> list[SplitEvent]:
        result = self._execute(self.client.table("split_events").select("*").eq("race_session_id", race_session_id).eq("is_deleted", False).order("event_order", desc=False), "Could not list active split events.")
        return [_split_event_from_row(row) for row in getattr(result, "data", [])]

    def list_all_split_events(self, race_session_id: str) -> list[SplitEvent]:
        result = self._execute(self.client.table("split_events").select("*").eq("race_session_id", race_session_id).order("event_order", desc=False), "Could not list split events.")
        return [_split_event_from_row(row) for row in getattr(result, "data", [])]

    def soft_delete_split_event(self, split_event_id: str) -> SplitEvent:
        updated_at = utc_now().isoformat()
        row = self._single(self.client.table("split_events").update({"is_deleted": True, "updated_at": updated_at}).eq("id", split_event_id), "Could not undo split event.")
        if row is None:
            raise RepositoryError("Split event not found.")
        return _split_event_from_row(row)

    def restore_split_event(self, split_event_id: str) -> SplitEvent:
        updated_at = utc_now().isoformat()
        row = self._single(self.client.table("split_events").update({"is_deleted": False, "updated_at": updated_at}).eq("id", split_event_id), "Could not restore split event.")
        if row is None:
            raise RepositoryError("Split event not found.")
        return _split_event_from_row(row)

    def create_race_session_checkpoints(self, race_session_id: str, checkpoints: list[Checkpoint]) -> list[RaceSessionCheckpoint]:
        if self.get_race_session(race_session_id) is None:
            raise RepositoryError("Race session not found.")
        existing = self.list_race_session_checkpoints(race_session_id)
        if existing:
            return existing
        rows = [_session_checkpoint_to_row(_session_checkpoint_from_checkpoint(race_session_id, checkpoint)) for checkpoint in checkpoints]
        self._execute(self.client.table("race_session_checkpoints").insert(rows), "Could not create race session checkpoint snapshot.")
        return self.list_race_session_checkpoints(race_session_id)

    def list_race_session_checkpoints(self, race_session_id: str) -> list[RaceSessionCheckpoint]:
        result = self._execute(
            self.client.table("race_session_checkpoints").select("*").eq("race_session_id", race_session_id).order("checkpoint_sequence", desc=False),
            "Could not list race session checkpoint snapshot.",
        )
        return [_session_checkpoint_from_row(row) for row in getattr(result, "data", [])]

    def delete_race_session(self, race_session_id: str) -> bool:
        if self.get_race_session(race_session_id) is None:
            return False
        self._execute(self.client.table("race_sessions").delete().eq("id", race_session_id), "Could not delete race session.")
        return True

    def delete_all_timing_data(self) -> bool:
        sessions = self._execute(self.client.table("race_sessions").select("id"), "Could not inspect timing sessions.")
        events = self._execute(self.client.table("split_events").select("id"), "Could not inspect split events.")
        had_data = bool(getattr(sessions, "data", []) or getattr(events, "data", []))
        self._execute(self.client.table("race_sessions").delete().neq("id", DELETE_ALL_FILTER_SENTINEL), "Could not delete timing sessions.")
        return had_data

    def delete_all_race_rosters(self) -> bool:
        rosters = self._execute(self.client.table("race_athletes").select("id"), "Could not inspect race rosters.")
        had_data = bool(getattr(rosters, "data", []))
        self._execute(self.client.table("race_athletes").delete().neq("id", DELETE_ALL_FILTER_SENTINEL), "Could not delete race rosters.")
        return had_data

    def delete_all_application_test_data(self) -> bool:
        meets = self._execute(self.client.table("meets").select("id"), "Could not inspect meets.")
        sessions = self._execute(self.client.table("race_sessions").select("id"), "Could not inspect timing sessions.")
        rosters = self._execute(self.client.table("race_athletes").select("id"), "Could not inspect race rosters.")
        had_data = bool(getattr(meets, "data", []) or getattr(sessions, "data", []) or getattr(rosters, "data", []))
        self._execute(self.client.table("race_sessions").delete().neq("id", DELETE_ALL_FILTER_SENTINEL), "Could not delete timing sessions.")
        self._execute(self.client.table("meets").delete().neq("id", DELETE_ALL_FILTER_SENTINEL), "Could not delete meets and races.")
        return had_data


def create_repository(
    *,
    connection_result: SupabaseConnectionResult | None = None,
    in_memory_repository: InMemoryRaceRepository | None = None,
) -> RepositoryFactoryResult:
    """Create the configured repository and report storage behavior."""
    config = load_supabase_config()
    if not config.is_configured:
        repository = in_memory_repository or InMemoryRaceRepository()
        repository.seed_default_xc_template()
        return RepositoryFactoryResult(repository=repository, storage_label="Temporary in-memory storage", is_temporary=True, message="Supabase is not configured; meet data will reset when the session ends.")

    try:
        connection = connection_result or create_supabase_connection(config)
    except Exception as exc:
        return RepositoryFactoryResult(repository=None, storage_label="Supabase unavailable", is_temporary=False, message="Supabase is configured but unavailable.", error=str(exc))
    if not connection.configured or connection.client is None:
        return RepositoryFactoryResult(repository=None, storage_label="Supabase unavailable", is_temporary=False, message="Supabase is configured but no client was created.", error=connection.message)
    repository = SupabaseRaceRepository(connection.client)
    try:
        repository.seed_default_xc_template()
    except RepositoryError as exc:
        return RepositoryFactoryResult(repository=None, storage_label="Supabase unavailable", is_temporary=False, message="Supabase is configured but initialization failed.", error=str(exc))
    return RepositoryFactoryResult(repository=repository, storage_label="Supabase", is_temporary=False, message="Meet data is stored in Supabase.")
