"""Repository abstractions for Phase 1 meet and race persistence."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from split_tracker.config import load_supabase_config
from split_tracker.supabase_client import SupabaseConnectionResult, create_supabase_connection

MEET_STATUSES = {"draft", "active", "upcoming", "completed", "archived"}
RACE_STATUSES = {"draft", "ready", "running", "paused", "completed", "archived"}
TEMPLATE_STATUSES = {"active", "archived"}
DEFAULT_XC_TEMPLATE_NAME = "Default XC Meet"
DEFAULT_XC_RACES = ["Boys JV", "Girls JV", "Boys Varsity", "Girls Varsity"]


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
    def create_race(self, race: Race) -> Race: ...
    def update_race(self, race: Race) -> Race: ...
    def get_race(self, race_id: str) -> Race | None: ...
    def list_races_for_meet(self, meet_id: str) -> list[Race]: ...
    def duplicate_race(self, race_id: str) -> Race: ...
    def archive_race(self, race_id: str) -> Race: ...
    def delete_draft_race(self, race_id: str) -> bool: ...
    def create_template(self, template: MeetTemplate, races: list[TemplateRace] | None = None) -> MeetTemplate: ...
    def update_template(self, template: MeetTemplate) -> MeetTemplate: ...
    def get_template(self, template_id: str) -> MeetTemplate | None: ...
    def list_templates(self, *, include_archived: bool = False) -> list[MeetTemplate]: ...
    def list_template_races(self, template_id: str) -> list[TemplateRace]: ...
    def apply_template_to_meet(self, template_id: str, meet: Meet) -> tuple[Meet, list[Race]]: ...
    def archive_template(self, template_id: str) -> MeetTemplate: ...
    def seed_default_xc_template(self) -> MeetTemplate: ...


class InMemoryRaceRepository:
    """In-session repository used when Supabase configuration is missing."""

    def __init__(self) -> None:
        self.meets: dict[str, Meet] = {}
        self.races: dict[str, Race] = {}
        self.templates: dict[str, MeetTemplate] = {}
        self.template_races: dict[str, TemplateRace] = {}

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
        for race in list(self.races.values()):
            if race.meet_id == meet_id:
                self.races.pop(race.id)
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
        self.races.pop(race_id)
        return True

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


class SupabaseRaceRepository:
    """Supabase-backed repository using the official Python client."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def _execute(self, operation: Any, message: str) -> Any:
        try:
            return operation.execute()
        except Exception as exc:
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
        self._execute(self.client.table("meets").delete().eq("id", meet_id), "Could not delete draft meet.")
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
        self._execute(self.client.table("races").delete().eq("id", race_id), "Could not delete draft race.")
        return True

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
