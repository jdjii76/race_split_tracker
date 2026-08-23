"""Repository abstractions for Phase 1 meet and race persistence."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from split_tracker.config import load_supabase_config
from split_tracker.branding import DEFAULT_SCHOOL_PROFILE, SchoolProfile
from split_tracker.models import Athlete, Checkpoint, PermanentAthlete
from split_tracker.athletes import normalize_athlete
from split_tracker.supabase_client import SupabaseConnectionResult, create_supabase_connection

MEET_STATUSES = {"draft", "active", "upcoming", "completed", "archived"}
RACE_STATUSES = {"draft", "ready", "running", "paused", "completed", "archived"}
RACE_SESSION_STATUSES = {"ready", "running", "paused", "awaiting_review", "completed", "cancelled"}
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
    course_id: str | None = None


@dataclass(frozen=True)
class Course:
    course_name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    location: str = ""
    distance_meters: float | None = None
    notes: str = ""
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
    recorded_by: str = ""
    is_deleted: bool = False
    recorded_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    correction_type: str = ""
    corrected_at: datetime | None = None
    corrected_by: str = ""
    event_type: str = "split_recorded"
    target_event_id: str | None = None
    corrects_event_id: str | None = None
    reason: str = ""
    client_event_id: str | None = None
    captured_at: datetime | None = None
    received_at: datetime | None = None
    capture_mode: str = "normal"
    device_id: str = ""
    capture_sequence: int | None = None
    clock_offset_ms: float | None = None


@dataclass(frozen=True)
class RaceAthleteOutcome:
    race_session_id: str
    athlete_id: str
    status: str = "dnf"
    recorded_by: str = ""
    recorded_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class ResultEvent:
    """Append-only post-race result assertion; the chain head is canonical."""

    race_session_id: str
    athlete_id: str
    status: str
    source: str
    id: str = field(default_factory=lambda: str(uuid4()))
    finish_seconds: float | None = None
    splits: dict[int, float] = field(default_factory=dict)
    note: str = ""
    supersedes_id: str | None = None
    created_by: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class SchoolSponsor:
    school_profile_id: str
    name: str
    logo_path: str
    id: str = field(default_factory=lambda: str(uuid4()))
    website_url: str = ""
    display_order: int = 0
    is_active: bool = True
    logo_url: str = ""
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

    def __init__(self, message: str, *, diagnostic: str = "") -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


def _safe_repository_diagnostic(exc: Exception) -> str:
    """Return bounded Supabase error metadata without requests or credentials."""
    parts: list[str] = []
    for label, attribute in (("Code", "code"), ("Message", "message"), ("Details", "details"), ("Hint", "hint")):
        value = getattr(exc, attribute, None)
        if value:
            text = " ".join(str(value).split())[:500]
            parts.append(f"{label}: {text}")
    if not parts:
        parts.append("Message: No structured Supabase diagnostic was provided.")
    return "\n".join(parts)


def _raise_authorization_error(exc: Exception) -> None:
    detail = str(exc).lower()
    if any(term in detail for term in ("not authorized", "permission denied", "jwt expired", "row-level security", "42501")):
        raise RepositoryError("Your coach session has expired or lacks permission. Sign in again.") from exc


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
    def list_courses(self) -> list[Course]: ...
    def create_course(self, course: Course) -> Course: ...
    def update_course(self, course: Course) -> Course: ...
    def list_race_athletes(self, race_id: str, *, include_inactive: bool = False) -> list[Athlete]: ...
    def replace_race_athletes(self, race_id: str, athletes: list[Athlete]) -> list[Athlete]: ...
    def delete_race_athlete(self, race_id: str, athlete_id: str) -> bool: ...
    def clear_race_roster(self, race_id: str) -> bool: ...
    def list_athletes(self, *, status: str | None = None, graduation_year: int | None = None, gender: str | None = None, team_division: str | None = None, search: str | None = None, include_archived: bool = False) -> list[PermanentAthlete]: ...
    def get_athlete(self, athlete_id: str) -> PermanentAthlete | None: ...
    def create_athlete(self, athlete: PermanentAthlete) -> PermanentAthlete: ...
    def update_athlete(self, athlete: PermanentAthlete) -> PermanentAthlete: ...
    def set_athlete_status(self, athlete_id: str, status: str) -> PermanentAthlete: ...
    def athlete_has_race_history(self, athlete_id: str) -> bool: ...
    def archive_athlete(self, athlete_id: str) -> PermanentAthlete: ...
    def restore_athlete(self, athlete_id: str) -> PermanentAthlete: ...
    def delete_unused_athlete(self, athlete_id: str) -> bool: ...
    def list_race_athlete_ids(self, race_id: str) -> list[str]: ...
    def replace_race_athletes_from_roster(self, race_id: str, athlete_ids: list[str]) -> list[Athlete]: ...
    def create_template(self, template: MeetTemplate, races: list[TemplateRace] | None = None) -> MeetTemplate: ...
    def update_template(self, template: MeetTemplate) -> MeetTemplate: ...
    def get_template(self, template_id: str) -> MeetTemplate | None: ...
    def list_templates(self, *, include_archived: bool = False) -> list[MeetTemplate]: ...
    def list_template_races(self, template_id: str) -> list[TemplateRace]: ...
    def apply_template_to_meet(self, template_id: str, meet: Meet) -> tuple[Meet, list[Race]]: ...
    def archive_template(self, template_id: str) -> MeetTemplate: ...
    def seed_default_xc_template(self) -> MeetTemplate: ...
    def get_school_profile(self) -> SchoolProfile | None: ...
    def get_school_profile_id(self) -> str: ...
    def save_school_profile(self, profile: SchoolProfile) -> SchoolProfile: ...
    def restore_default_school_profile(self) -> SchoolProfile: ...
    def upload_branding_asset(self, object_path: str, content: bytes, content_type: str) -> str: ...
    def get_branding_asset_url(self, object_path: str) -> str | None: ...
    def list_sponsors(self, school_profile_id: str | None = None) -> list[SchoolSponsor]: ...
    def list_active_sponsors(self, school_profile_id: str | None = None) -> list[SchoolSponsor]: ...
    def get_sponsor(self, sponsor_id: str) -> SchoolSponsor | None: ...
    def create_sponsor(self, sponsor: SchoolSponsor) -> SchoolSponsor: ...
    def update_sponsor(self, sponsor: SchoolSponsor) -> SchoolSponsor: ...
    def delete_sponsor(self, sponsor_id: str) -> bool: ...

    def create_race_session(self, session: RaceSession) -> RaceSession: ...
    def create_started_race_session_with_checkpoints(self, session: RaceSession, checkpoints: list[Checkpoint]) -> RaceSession: ...
    def get_or_create_active_race_session(self, race_id: str, checkpoints: list[Checkpoint]) -> RaceSession: ...
    def get_race_session(self, race_session_id: str) -> RaceSession | None: ...
    def start_race_session(self, race_session_id: str, started_at: datetime) -> RaceSession: ...
    def get_active_or_latest_race_session_for_race(self, race_id: str) -> RaceSession | None: ...
    def transition_race_session(self, race_session_id: str, action: str) -> RaceSession: ...
    def complete_race_timing(self, race_session_id: str, finish_checkpoint_number: int | None = None) -> RaceSession: ...
    def finalize_race_session(self, race_session_id: str) -> RaceSession: ...
    def reopen_race_session(self, race_session_id: str) -> RaceSession: ...
    def list_race_athlete_outcomes(self, race_session_id: str) -> list[RaceAthleteOutcome]: ...
    def set_race_athlete_dnf(self, race_session_id: str, athlete_id: str, recorded_by: str) -> RaceAthleteOutcome: ...
    def clear_race_athlete_dnf(self, race_session_id: str, athlete_id: str) -> bool: ...
    def save_post_race_result(self, event: ResultEvent) -> ResultEvent: ...
    def list_result_events(self, race_session_id: str, athlete_id: str | None = None) -> list[ResultEvent]: ...
    def update_race_session(self, session: RaceSession) -> RaceSession: ...
    def list_race_sessions_for_race(self, race_id: str) -> list[RaceSession]: ...
    def list_race_sessions_for_races(self, race_ids: list[str]) -> list[RaceSession]: ...
    def count_race_athletes_for_races(self, race_ids: list[str]) -> dict[str, int]: ...
    def create_split_event(self, event: SplitEvent) -> SplitEvent: ...
    def record_shared_split(self, race_session_id: str, athlete_id: str, checkpoint_number: int, recorded_by: str, request_id: str) -> SplitEvent: ...
    def record_pack_split_events(self, race_session_id: str, events: list[dict[str, Any]], recorded_by: str) -> list[SplitEvent]: ...
    def list_active_split_events(self, race_session_id: str) -> list[SplitEvent]: ...
    def list_all_split_events(self, race_session_id: str) -> list[SplitEvent]: ...
    def soft_delete_split_event(self, split_event_id: str) -> SplitEvent: ...
    def invalidate_split_event(self, split_event_id: str, race_session_id: str, athlete_id: str, checkpoint_number: int, corrected_by: str, *, require_latest: bool = False) -> SplitEvent: ...
    def correct_split_athlete(self, split_event_id: str, race_session_id: str, athlete_id: str, checkpoint_number: int, new_athlete_id: str, corrected_by: str, request_id: str) -> list[SplitEvent]: ...
    def record_manual_split(self, race_session_id: str, athlete_id: str, checkpoint_number: int, elapsed_seconds: float, recorded_by: str, request_id: str) -> SplitEvent: ...
    def list_recent_split_events(self, race_session_id: str, *, limit: int = 10) -> list[SplitEvent]: ...
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
        self.race_athlete_outcomes: dict[tuple[str, str], RaceAthleteOutcome] = {}
        self.result_events: dict[str, ResultEvent] = {}
        self.race_athletes: dict[tuple[str, str], Athlete] = {}
        self.school_profile: SchoolProfile | None = None
        self.athletes: dict[str, PermanentAthlete] = {}
        self.sponsors: dict[str, SchoolSponsor] = {}
        self.courses: dict[str, Course] = {}
        self._race_session_start_lock = threading.Lock()
        # Mirrors PostgreSQL's race_sessions row lock for lifecycle/split races.
        self._race_session_lock = threading.RLock()

    def get_school_profile(self) -> SchoolProfile | None:
        return self.school_profile

    def get_school_profile_id(self) -> str:
        return "default"

    def save_school_profile(self, profile: SchoolProfile) -> SchoolProfile:
        self.school_profile = profile
        return profile

    def restore_default_school_profile(self) -> SchoolProfile:
        return self.save_school_profile(DEFAULT_SCHOOL_PROFILE)

    def upload_branding_asset(self, object_path: str, content: bytes, content_type: str) -> str:
        raise RepositoryError("Logo uploads require configured Supabase Storage.")

    def get_branding_asset_url(self, object_path: str) -> str | None:
        return None

    def list_sponsors(self, school_profile_id=None) -> list[SchoolSponsor]:
        rows = list(self.sponsors.values())
        if school_profile_id is not None:
            rows = [item for item in rows if item.school_profile_id == school_profile_id]
        return sorted(rows, key=lambda item: (item.display_order, item.name.casefold(), item.id))

    def list_active_sponsors(self, school_profile_id=None) -> list[SchoolSponsor]:
        return [item for item in self.list_sponsors(school_profile_id) if item.is_active]

    def get_sponsor(self, sponsor_id: str) -> SchoolSponsor | None:
        return self.sponsors.get(sponsor_id)

    def create_sponsor(self, sponsor: SchoolSponsor) -> SchoolSponsor:
        if not sponsor.name.strip() or not sponsor.logo_path.strip() or sponsor.display_order < 0:
            raise RepositoryError("Sponsor name, logo, and non-negative display order are required.")
        saved = replace(sponsor, name=sponsor.name.strip(), updated_at=utc_now())
        self.sponsors[saved.id] = saved
        return saved

    def update_sponsor(self, sponsor: SchoolSponsor) -> SchoolSponsor:
        if sponsor.id not in self.sponsors: raise RepositoryError("Sponsor not found.")
        return self.create_sponsor(replace(sponsor, created_at=self.sponsors[sponsor.id].created_at))

    def delete_sponsor(self, sponsor_id: str) -> bool:
        return self.sponsors.pop(sponsor_id, None) is not None

    def list_athletes(self, *, status=None, graduation_year=None, gender=None, team_division=None, search=None, include_archived=False) -> list[PermanentAthlete]:
        athletes = list(self.athletes.values())
        if not include_archived and status != "archived": athletes = [item for item in athletes if item.status != "archived"]
        if status: athletes = [item for item in athletes if item.status == status]
        if graduation_year is not None: athletes = [item for item in athletes if item.graduation_year == graduation_year]
        if gender: athletes = [item for item in athletes if item.gender == gender]
        if team_division: athletes = [item for item in athletes if item.team_division == team_division]
        if search:
            term = search.casefold().strip()
            athletes = [item for item in athletes if term in item.display_name.casefold() or term in item.athlete_number.casefold()]
        return sorted(athletes, key=lambda item: (item.last_name.casefold(), item.first_name.casefold(), item.id))

    def get_athlete(self, athlete_id: str) -> PermanentAthlete | None:
        return self.athletes.get(athlete_id)

    def create_athlete(self, athlete: PermanentAthlete) -> PermanentAthlete:
        saved = normalize_athlete(athlete)
        if saved.id in self.athletes: raise RepositoryError("Athlete already exists.")
        self.athletes[saved.id] = saved
        return saved

    def update_athlete(self, athlete: PermanentAthlete) -> PermanentAthlete:
        if athlete.id not in self.athletes: raise RepositoryError("Athlete not found.")
        saved = replace(normalize_athlete(athlete), updated_at=utc_now())
        self.athletes[saved.id] = saved
        return saved

    def set_athlete_status(self, athlete_id: str, status: str) -> PermanentAthlete:
        athlete = self.get_athlete(athlete_id)
        if athlete is None: raise RepositoryError("Athlete not found.")
        return self.update_athlete(replace(athlete, status=status))

    def athlete_has_race_history(self, athlete_id: str) -> bool:
        """Check permanent UUID references without inspecting mutable names."""
        return any(stored_id == athlete_id for _, stored_id in self.race_athletes)

    def archive_athlete(self, athlete_id: str) -> PermanentAthlete:
        return self.set_athlete_status(athlete_id, "archived")

    def restore_athlete(self, athlete_id: str) -> PermanentAthlete:
        athlete = self.get_athlete(athlete_id)
        if athlete is None: raise RepositoryError("Athlete not found.")
        if athlete.status != "archived": raise RepositoryError("Only archived athletes can be restored.")
        return self.set_athlete_status(athlete_id, "active")

    def delete_unused_athlete(self, athlete_id: str) -> bool:
        if athlete_id not in self.athletes: raise RepositoryError("Athlete not found.")
        if self.athlete_has_race_history(athlete_id):
            raise RepositoryError("Athlete has race history and cannot be permanently deleted. Archive the athlete instead.")
        del self.athletes[athlete_id]
        return True

    def list_race_athlete_ids(self, race_id: str) -> list[str]:
        return [item.athlete_id for item in self.list_race_athletes(race_id, include_inactive=True) if item.athlete_id in self.athletes]

    def replace_race_athletes_from_roster(self, race_id: str, athlete_ids: list[str]) -> list[Athlete]:
        if len(athlete_ids) != len(set(athlete_ids)): raise RepositoryError("An athlete can only be selected once per race.")
        existing = {item.athlete_id: item for item in self.list_race_athletes(race_id, include_inactive=True)}
        removed = set(existing) - set(athlete_ids)
        if removed and any(session.started_at or self.list_all_split_events(session.id) for session in self.list_race_sessions_for_race(race_id)):
            raise RepositoryError("Athletes cannot be removed after timing has started or split events exist.")
        for athlete_id in removed: self.race_athletes.pop((race_id, athlete_id), None)
        for index, athlete_id in enumerate(athlete_ids):
            permanent = self.get_athlete(athlete_id)
            if permanent is None: raise RepositoryError("Selected permanent athlete was not found.")
            if permanent.status == "archived" and athlete_id not in existing:
                raise RepositoryError("Archived athletes cannot be added to a new race roster. Restore the athlete first.")
            snapshot = existing.get(athlete_id) or Athlete(name=permanent.display_name, athlete_id=permanent.id, gender=permanent.gender, team=permanent.team_division)
            self.race_athletes[(race_id, athlete_id)] = replace(snapshot, display_order=index)
        return self.list_race_athletes(race_id, include_inactive=True)

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

    def list_courses(self) -> list[Course]:
        return sorted(self.courses.values(), key=lambda item: (item.course_name.casefold(), item.id))

    def create_course(self, course: Course) -> Course:
        if not course.course_name.strip(): raise RepositoryError("Course name is required.")
        saved = replace(course, course_name=course.course_name.strip(), updated_at=utc_now())
        self.courses[saved.id] = saved
        return saved

    def update_course(self, course: Course) -> Course:
        if course.id not in self.courses: raise RepositoryError("Course not found.")
        return self.create_course(replace(course, created_at=self.courses[course.id].created_at))

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
        existing_ids = {item.athlete_id for item in self.list_race_athletes(race_id, include_inactive=True)}
        removed = existing_ids - {item.athlete_id for item in athletes}
        if removed and any(session.started_at or self.list_all_split_events(session.id) for session in self.list_race_sessions_for_race(race_id)):
            raise RepositoryError("Athletes cannot be removed after timing has started or split events exist.")
        for athlete_id in removed:
            self.race_athletes.pop((race_id, athlete_id), None)
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

    def get_or_create_active_race_session(self, race_id: str, checkpoints: list[Checkpoint]) -> RaceSession:
        """Atomically return the race's nonterminal session or create one."""
        if not checkpoints:
            raise RepositoryError("At least one checkpoint is required to start a race session.")
        self._require_race(race_id)
        with self._race_session_start_lock:
            active = [
                session for session in self.list_race_sessions_for_race(race_id)
                if session.status in {"ready", "running", "paused"}
            ]
            if active:
                session = active[-1]
                if session.status == "ready":
                    self.create_race_session_checkpoints(session.id, checkpoints)
                    session = self.update_race_session(
                        replace(session, status="running", started_at=session.started_at or utc_now())
                    )
                return session
            return self.create_started_race_session_with_checkpoints(
                RaceSession(race_id=race_id, status="running", started_at=utc_now()),
                checkpoints,
            )

    def get_race_session(self, race_session_id: str) -> RaceSession | None:
        return self.race_sessions.get(race_session_id)

    def start_race_session(self, race_session_id: str, started_at: datetime) -> RaceSession:
        """Start a ready session once, or return its existing authoritative start."""
        session = self.race_sessions.get(race_session_id)
        if session is None:
            raise RepositoryError("Race session not found.")
        if session.status in {"running", "paused"} and session.started_at is not None:
            return session
        if session.status != "ready" or session.started_at is not None:
            raise RepositoryError("Race session cannot be started from its current state.")
        return self.update_race_session(replace(session, status="running", started_at=started_at))

    def get_active_or_latest_race_session_for_race(self, race_id: str) -> RaceSession | None:
        sessions = self.list_race_sessions_for_race(race_id)
        active = [session for session in sessions if session.status in {"ready", "running", "paused"}]
        if active:
            return active[-1]
        return sessions[-1] if sessions else None

    def update_race_session(self, session: RaceSession) -> RaceSession:
        if session.id not in self.race_sessions:
            raise RepositoryError("Race session not found.")
        saved = replace(session, updated_at=utc_now())
        self.race_sessions[saved.id] = saved
        return saved

    def transition_race_session(self, race_session_id: str, action: str) -> RaceSession:
        """Model the locked, server-timed lifecycle RPC for local/test storage."""
        normalized = action.strip().lower()
        if normalized not in {"pause", "resume", "complete", "cancel"}:
            raise RepositoryError(f"Unknown race session action: {action}")
        with self._race_session_lock:
            session = self.race_sessions.get(race_session_id)
            if session is None:
                raise RepositoryError("Race session not found.")
            idempotent_status = {"pause": "paused", "resume": "running", "complete": "completed", "cancel": "cancelled"}[normalized]
            if session.status == idempotent_status:
                return session
            allowed = {"pause": {"running"}, "resume": {"paused"}, "complete": {"running", "paused"}, "cancel": {"ready", "running", "paused"}}[normalized]
            if session.status not in allowed:
                raise RepositoryError(f"Invalid race session transition: {normalized} from {session.status}.")
            server_now = utc_now()
            elapsed = session.elapsed_offset_seconds
            if session.status == "running" and session.started_at is not None:
                elapsed += max(0.0, (server_now - session.started_at).total_seconds())
            if normalized == "pause":
                saved = replace(session, status="paused", paused_at=server_now, elapsed_offset_seconds=elapsed)
            elif normalized == "resume":
                saved = replace(session, status="running", started_at=server_now, paused_at=None)
            elif normalized == "complete":
                saved = replace(session, status="completed", ended_at=server_now, paused_at=None, elapsed_offset_seconds=elapsed)
            else:
                saved = replace(session, status="cancelled", ended_at=server_now if session.started_at is not None else None, paused_at=None, elapsed_offset_seconds=elapsed)
            saved = replace(saved, updated_at=server_now)
            self.race_sessions[saved.id] = saved
            return saved

    def complete_race_timing(self, race_session_id: str, finish_checkpoint_number: int | None = None) -> RaceSession:
        """Stop capture without asserting that results are final."""
        with self._race_session_lock:
            session = self.get_race_session(race_session_id)
            if session is None:
                raise RepositoryError("Race session not found.")
            if finish_checkpoint_number is not None and not any(
                checkpoint.checkpoint_sequence == finish_checkpoint_number and checkpoint.is_finish
                for checkpoint in self.list_race_session_checkpoints(race_session_id)
            ):
                raise RepositoryError("Only the Finish Line timer can end race timing.")
            if session.status == "awaiting_review":
                return session
            if session.status not in {"running", "paused"}:
                raise RepositoryError("Race timing can only end from a running or paused session.")
            server_now = utc_now()
            elapsed = session.elapsed_offset_seconds
            if session.status == "running" and session.started_at is not None:
                elapsed += max(0.0, (server_now - session.started_at).total_seconds())
            saved = replace(
                session,
                status="awaiting_review",
                ended_at=server_now,
                paused_at=None,
                elapsed_offset_seconds=elapsed,
                updated_at=server_now,
            )
            self.race_sessions[saved.id] = saved
            return saved

    def finalize_race_session(self, race_session_id: str) -> RaceSession:
        """Complete only when every active roster athlete finished or is DNF."""
        with self._race_session_lock:
            session = self.get_race_session(race_session_id)
            if session is None: raise RepositoryError("Race session not found.")
            if session.status == "completed": return session
            if session.status not in {"running", "paused", "awaiting_review"}: raise RepositoryError("Race session cannot be finished from its current state.")
            finish_numbers = {item.checkpoint_sequence for item in self.list_race_session_checkpoints(race_session_id) if item.is_finish}
            finished_ids = {
                event.athlete_id for event in self.list_active_split_events(race_session_id)
                if event.checkpoint_number in finish_numbers
            }
            dnf_ids = {item.athlete_id for item in self.list_race_athlete_outcomes(race_session_id) if item.status == "dnf"}
            managed_ids = set(canonical_result_events(self.list_result_events(race_session_id)))
            roster_ids = {item.athlete_id for item in self.list_race_athletes(session.race_id)}
            if roster_ids - finished_ids - dnf_ids - managed_ids:
                raise RepositoryError("Resolve every unfinished athlete before finishing the race.")
            if session.status == "awaiting_review":
                return self.update_race_session(replace(session, status="completed", updated_at=utc_now()))
            return self.transition_race_session(race_session_id, "complete")

    def reopen_race_session(self, race_session_id: str) -> RaceSession:
        """Reopen the same completed session in a safe paused state."""
        with self._race_session_lock:
            session = self.get_race_session(race_session_id)
            if session is None: raise RepositoryError("Race session not found.")
            if session.status in {"running", "paused"}: return session
            if session.status != "completed": raise RepositoryError("Only a completed race session can be reopened.")
            saved = replace(session, status="paused", ended_at=None, paused_at=utc_now(), updated_at=utc_now())
            self.race_sessions[saved.id] = saved
            return saved

    def list_race_athlete_outcomes(self, race_session_id: str) -> list[RaceAthleteOutcome]:
        return sorted(
            [item for (session_id, _), item in self.race_athlete_outcomes.items() if session_id == race_session_id],
            key=lambda item: (item.recorded_at, item.athlete_id),
        )

    def set_race_athlete_dnf(self, race_session_id: str, athlete_id: str, recorded_by: str) -> RaceAthleteOutcome:
        with self._race_session_lock:
            session = self.get_race_session(race_session_id)
            if session is None: raise RepositoryError("Race session not found.")
            if session.status not in {"running", "paused"}: raise RepositoryError("Reopen the race before changing athlete outcomes.")
            if athlete_id not in {item.athlete_id for item in self.list_race_athletes(session.race_id)}:
                raise RepositoryError("Athlete does not belong to this race session.")
            finish_numbers = {item.checkpoint_sequence for item in self.list_race_session_checkpoints(race_session_id) if item.is_finish}
            if any(event.athlete_id == athlete_id and event.checkpoint_number in finish_numbers for event in self.list_active_split_events(race_session_id)):
                raise RepositoryError("A finished athlete cannot be marked DNF.")
            outcome = RaceAthleteOutcome(race_session_id, athlete_id, recorded_by=recorded_by.strip())
            self.race_athlete_outcomes[(race_session_id, athlete_id)] = outcome
            return outcome

    def clear_race_athlete_dnf(self, race_session_id: str, athlete_id: str) -> bool:
        with self._race_session_lock:
            session = self.get_race_session(race_session_id)
            if session is None: raise RepositoryError("Race session not found.")
            if session.status not in {"running", "paused"}: raise RepositoryError("Reopen the race before changing athlete outcomes.")
            return self.race_athlete_outcomes.pop((race_session_id, athlete_id), None) is not None

    def list_result_events(self, race_session_id: str, athlete_id: str | None = None) -> list[ResultEvent]:
        return sorted(
            (event for event in self.result_events.values()
             if event.race_session_id == race_session_id and (athlete_id is None or event.athlete_id == athlete_id)),
            key=lambda event: (event.created_at, event.id),
        )

    def save_post_race_result(self, event: ResultEvent) -> ResultEvent:
        """Append a result without changing the finalized race lifecycle."""
        with self._race_session_lock:
            session = self.get_race_session(event.race_session_id)
            if session is None or session.status not in {"awaiting_review", "completed"}:
                raise RepositoryError("Results can only be managed after race timing ends.")
            if event.athlete_id not in {a.athlete_id for a in self.list_race_athletes(session.race_id, include_inactive=True)}:
                raise RepositoryError("Athlete does not belong to this race.")
            _validate_result_event(event)
            current = canonical_result_events(self.list_result_events(session.id)).get(event.athlete_id)
            if current and event.supersedes_id != current.id:
                raise RepositoryError("This result changed since it was loaded. Refresh and try again.")
            if not current and event.supersedes_id:
                raise RepositoryError("The superseded result is not current.")
            saved = replace(event, finish_seconds=round(event.finish_seconds, 2) if event.finish_seconds else None,
                            splits={int(k): round(float(v), 2) for k, v in event.splits.items()})
            self.result_events[saved.id] = saved
            return saved

    def list_race_sessions_for_race(self, race_id: str) -> list[RaceSession]:
        return sorted([session for session in self.race_sessions.values() if session.race_id == race_id], key=lambda session: (session.created_at, session.id))

    def list_race_sessions_for_races(self, race_ids: list[str]) -> list[RaceSession]:
        """Return sessions for several races in one repository operation."""
        wanted = set(race_ids)
        return sorted(
            [session for session in self.race_sessions.values() if session.race_id in wanted],
            key=lambda session: (session.created_at, session.id),
        )

    def count_race_athletes_for_races(self, race_ids: list[str]) -> dict[str, int]:
        """Return active snapshot counts keyed by stable race UUID."""
        counts = {race_id: 0 for race_id in race_ids}
        for (race_id, _), athlete in self.race_athletes.items():
            if race_id in counts and athlete.active:
                counts[race_id] += 1
        return counts

    def create_split_event(self, event: SplitEvent) -> SplitEvent:
        session = self.race_sessions.get(event.race_session_id)
        if session is None:
            raise RepositoryError("Race session not found.")
        if any(existing.athlete_id == event.athlete_id and existing.checkpoint_number == event.checkpoint_number
               for existing in self.list_active_split_events(event.race_session_id)):
            raise RepositoryError("That athlete already has an active split at this checkpoint.")
        saved = replace(event, created_at=event.created_at, updated_at=utc_now())
        self.split_events[saved.id] = saved
        return saved

    def record_shared_split(self, race_session_id: str, athlete_id: str, checkpoint_number: int, recorded_by: str, request_id: str) -> SplitEvent:
        """Model the server-authoritative split RPC for local/test storage."""
        with self._race_session_lock:
            existing = self.split_events.get(request_id)
            if existing is not None:
                if existing.race_session_id != race_session_id or existing.athlete_id != athlete_id:
                    raise RepositoryError("Split request ID belongs to a different action.")
                return existing
            session = self.race_sessions.get(race_session_id)
            if session is None:
                raise RepositoryError("Race session not found.")
            if session.status != "running" or session.started_at is None:
                raise RepositoryError("Race session is not running.")
            if (race_session_id, athlete_id) in self.race_athlete_outcomes:
                raise RepositoryError("Reverse DNF before recording another split.")
            athlete = next(
                (item for item in self.list_race_athletes(session.race_id) if item.athlete_id == athlete_id),
                None,
            )
            if athlete is None:
                raise RepositoryError("Invalid athlete for this race session.")
            checkpoints = self.list_race_session_checkpoints(race_session_id)
            completed = len([
                event for event in self.split_events.values()
                if event.race_session_id == race_session_id
                and event.athlete_id == athlete_id
                and not event.is_deleted
            ])
            if completed >= len(checkpoints):
                raise RepositoryError("Athlete has no remaining checkpoint.")
            checkpoint = checkpoints[completed]
            if checkpoint.checkpoint_sequence != checkpoint_number:
                raise RepositoryError("Unexpected checkpoint progression.")
            recorded_at = utc_now()
            elapsed = max(
                0.0,
                session.elapsed_offset_seconds
                + (recorded_at - session.started_at).total_seconds(),
            )
            event_order = max(
                [event.event_order for event in self.split_events.values() if event.race_session_id == race_session_id]
                or [0]
            ) + 1
            return self.create_split_event(SplitEvent(
                id=request_id,
                race_session_id=race_session_id,
                athlete_id=athlete_id,
                athlete_name=athlete.name,
                bib_number=athlete.bib_number,
                checkpoint_number=checkpoint.checkpoint_sequence,
                checkpoint_label=checkpoint.label,
                elapsed_seconds=elapsed,
                event_order=event_order,
                recorded_by=recorded_by,
                recorded_at=recorded_at,
            ))

    def record_pack_split_events(self, race_session_id: str, events: list[dict[str, Any]], recorded_by: str) -> list[SplitEvent]:
        """Atomically validate captured client times and append an idempotent pack."""
        saved: list[SplitEvent] = []
        with self._race_session_lock:
            session = self.race_sessions.get(race_session_id)
            if session is None or session.status != "running" or session.started_at is None:
                raise RepositoryError("Race session is not running.")
            ordered = sorted(events, key=lambda item: (item["captured_at"], int(item["capture_sequence"]), item["client_event_id"]))
            for item in ordered:
                event_id = str(item["client_event_id"])
                existing = self.split_events.get(event_id)
                if existing:
                    if existing.race_session_id != race_session_id or existing.athlete_id != str(item["athlete_id"]):
                        raise RepositoryError("Pack event ID belongs to a different action.")
                    saved.append(existing); continue
                athlete = next((a for a in self.list_race_athletes(session.race_id) if a.athlete_id == str(item["athlete_id"])), None)
                checkpoint = next((c for c in self.list_race_session_checkpoints(race_session_id) if c.checkpoint_sequence == int(item["checkpoint_number"])), None)
                if athlete is None or checkpoint is None:
                    raise RepositoryError("Invalid athlete or checkpoint for this race session.")
                captured = item["captured_at"]
                if isinstance(captured, str): captured = datetime.fromisoformat(captured.replace("Z", "+00:00"))
                elapsed = max(0.0, session.elapsed_offset_seconds + (captured - session.started_at).total_seconds())
                conflict = any(e.athlete_id == athlete.athlete_id and e.checkpoint_number == checkpoint.checkpoint_sequence for e in self.list_active_split_events(race_session_id))
                event = SplitEvent(id=event_id, race_session_id=race_session_id, athlete_id=athlete.athlete_id,
                    athlete_name=athlete.name, bib_number=athlete.bib_number, checkpoint_number=checkpoint.checkpoint_sequence,
                    checkpoint_label=checkpoint.label, elapsed_seconds=elapsed,
                    event_order=max([e.event_order for e in self.list_all_split_events(race_session_id)] or [0])+1,
                    recorded_by=recorded_by, recorded_at=captured, client_event_id=event_id, captured_at=captured,
                    received_at=utc_now(), capture_mode="pack", device_id=str(item.get("device_id", "")),
                    capture_sequence=int(item["capture_sequence"]), clock_offset_ms=float(item.get("clock_offset_ms", 0)),
                    event_type="pack_conflict" if conflict else "split_recorded", reason="duplicate logical split" if conflict else "")
                # Conflicts remain in audit history but projection excludes them.
                self.split_events[event.id] = event
                saved.append(event)
        return saved

    def list_active_split_events(self, race_session_id: str) -> list[SplitEvent]:
        events = self.list_all_split_events(race_session_id)
        inactive = {event.target_event_id for event in events if event.event_type == "split_voided" and event.target_event_id}
        return [event for event in events if event.event_type not in {"split_voided", "pack_conflict"} and not event.is_deleted and event.id not in inactive]

    def list_all_split_events(self, race_session_id: str) -> list[SplitEvent]:
        return sorted(
            [event for event in self.split_events.values() if event.race_session_id == race_session_id],
            key=_split_event_order_key,
        )

    def soft_delete_split_event(self, split_event_id: str) -> SplitEvent:
        event = self._require_split_event(split_event_id)
        saved = replace(event, is_deleted=True, updated_at=utc_now())
        self.split_events[saved.id] = saved
        return saved

    def invalidate_split_event(self, split_event_id: str, race_session_id: str, athlete_id: str, checkpoint_number: int, corrected_by: str, *, require_latest: bool = False) -> SplitEvent:
        """Atomically validate and invalidate one exact session event."""
        with self._race_session_lock:
            return self._invalidate_split_event_locked(split_event_id, race_session_id, athlete_id, checkpoint_number, corrected_by, require_latest)

    def _invalidate_split_event_locked(self, split_event_id: str, race_session_id: str, athlete_id: str, checkpoint_number: int, corrected_by: str, require_latest: bool) -> SplitEvent:
        session = self.get_race_session(race_session_id)
        if session is None: raise RepositoryError("Race session not found.")
        if session.status == "completed": raise RepositoryError("Reopen the race before changing split history.")
        event = self._require_split_event(split_event_id)
        if event.race_session_id != race_session_id or event.athlete_id != athlete_id or event.checkpoint_number != checkpoint_number:
            raise RepositoryError("Split correction no longer matches the selected race-session event.")
        if event.is_deleted or event.id not in {item.id for item in self.list_active_split_events(race_session_id)}:
            raise RepositoryError("That split was already corrected by another user.")
        if require_latest and any(
            item.race_session_id == race_session_id and not item.is_deleted and item.event_order > event.event_order
            for item in self.split_events.values()
        ):
            raise RepositoryError("A newer split was recorded. Refresh before choosing Undo Last Split.")
        corrected_at = utc_now()
        saved = SplitEvent(
            race_session_id=race_session_id, athlete_id=event.athlete_id,
            athlete_name=event.athlete_name, bib_number=event.bib_number,
            checkpoint_number=event.checkpoint_number, checkpoint_label=event.checkpoint_label,
            elapsed_seconds=event.elapsed_seconds,
            event_order=max([item.event_order for item in self.list_all_split_events(race_session_id)] or [0]) + 1,
            recorded_by=corrected_by.strip(), recorded_at=corrected_at,
            correction_type="invalidated", corrected_at=corrected_at,
            corrected_by=corrected_by.strip(), event_type="split_voided",
            target_event_id=event.id, reason="undo",
        )
        self.split_events[saved.id] = saved
        return saved

    def correct_split_athlete(self, split_event_id: str, race_session_id: str, athlete_id: str, checkpoint_number: int, new_athlete_id: str, corrected_by: str, request_id: str) -> list[SplitEvent]:
        """Atomically void a split and append a timestamp-preserving reassignment."""
        with self._race_session_lock:
            target = self._require_split_event(split_event_id)
            if target.race_session_id != race_session_id or target.athlete_id != athlete_id or target.checkpoint_number != checkpoint_number:
                raise RepositoryError("Split correction no longer matches the selected race-session event.")
            active = self.list_active_split_events(race_session_id)
            if target.id not in {item.id for item in active}:
                raise RepositoryError("That split was already changed by another coach.")
            session = self.get_race_session(race_session_id)
            destination = next((item for item in self.list_race_athletes(session.race_id) if item.athlete_id == new_athlete_id), None) if session else None
            if destination is None: raise RepositoryError("Invalid athlete for this race session.")
            if any(item.athlete_id == new_athlete_id and item.checkpoint_number == checkpoint_number for item in active):
                raise RepositoryError(f"{destination.name} already has a {target.checkpoint_label} split.")
            voided = self._invalidate_split_event_locked(split_event_id, race_session_id, athlete_id, checkpoint_number, corrected_by, False)
            replacement = SplitEvent(
                id=request_id, race_session_id=race_session_id, athlete_id=new_athlete_id,
                athlete_name=destination.name, bib_number=destination.bib_number,
                checkpoint_number=target.checkpoint_number, checkpoint_label=target.checkpoint_label,
                elapsed_seconds=target.elapsed_seconds, event_order=voided.event_order + 1,
                recorded_by=corrected_by.strip(), recorded_at=target.recorded_at,
                correction_type="manual", corrected_at=utc_now(), corrected_by=corrected_by.strip(),
                event_type="split_corrected", corrects_event_id=target.id, reason="wrong athlete",
            )
            self.split_events[replacement.id] = replacement
            return [voided, replacement]

    def record_manual_split(self, race_session_id: str, athlete_id: str, checkpoint_number: int, elapsed_seconds: float, recorded_by: str, request_id: str) -> SplitEvent:
        """Insert the athlete's exact next missing checkpoint with entered elapsed time."""
        with self._race_session_lock:
            return self._record_manual_split_locked(race_session_id, athlete_id, checkpoint_number, elapsed_seconds, recorded_by, request_id)

    def _record_manual_split_locked(self, race_session_id: str, athlete_id: str, checkpoint_number: int, elapsed_seconds: float, recorded_by: str, request_id: str) -> SplitEvent:
        session = self.get_race_session(race_session_id)
        if session is None: raise RepositoryError("Race session not found.")
        if session.status not in {"running", "paused"}: raise RepositoryError("Missed splits can only be added to a running or paused race.")
        if (race_session_id, athlete_id) in self.race_athlete_outcomes: raise RepositoryError("Reverse DNF before recording another split.")
        athlete = next((item for item in self.list_race_athletes(session.race_id) if item.athlete_id == athlete_id), None)
        if athlete is None: raise RepositoryError("Invalid athlete for this race session.")
        checkpoints = self.list_race_session_checkpoints(race_session_id)
        active = [event for event in self.list_active_split_events(race_session_id) if event.athlete_id == athlete_id]
        if request_id in self.split_events:
            existing = self.split_events[request_id]
            if existing.race_session_id == race_session_id and existing.athlete_id == athlete_id and existing.checkpoint_number == checkpoint_number:
                return existing
            raise RepositoryError("Split request ID belongs to a different action.")
        by_checkpoint = {event.checkpoint_number: event for event in active}
        expected = next((checkpoint for checkpoint in checkpoints if checkpoint.checkpoint_sequence not in by_checkpoint), None)
        if expected is None or expected.checkpoint_sequence != checkpoint_number:
            raise RepositoryError("Manual split must be the athlete's next missing checkpoint.")
        previous = [event.elapsed_seconds for event in active if event.checkpoint_number < checkpoint_number]
        later = [event.elapsed_seconds for event in active if event.checkpoint_number > checkpoint_number]
        if elapsed_seconds < 0 or (previous and elapsed_seconds <= max(previous)) or (later and elapsed_seconds >= min(later)):
            raise RepositoryError("Manual elapsed time must fall between the athlete's surrounding splits.")
        current_elapsed = session.elapsed_offset_seconds
        if session.status == "running" and session.started_at is not None:
            current_elapsed += max(0.0, (utc_now() - session.started_at).total_seconds())
        if elapsed_seconds > current_elapsed:
            raise RepositoryError("Manual elapsed time cannot be later than the authoritative race clock.")
        corrected_at = utc_now()
        saved = SplitEvent(
            id=request_id,
            race_session_id=race_session_id,
            athlete_id=athlete_id,
            athlete_name=athlete.name,
            bib_number=athlete.bib_number,
            checkpoint_number=expected.checkpoint_sequence,
            checkpoint_label=expected.label,
            elapsed_seconds=elapsed_seconds,
            event_order=max([event.event_order for event in self.list_all_split_events(race_session_id)] or [0]) + 1,
            recorded_by=recorded_by.strip(),
            correction_type="manual",
            event_type="split_manual",
            corrected_at=corrected_at,
            corrected_by=recorded_by.strip(),
        )
        self.split_events[saved.id] = saved
        return saved

    def list_recent_split_events(self, race_session_id: str, *, limit: int = 10) -> list[SplitEvent]:
        events = self.list_all_split_events(race_session_id)
        return sorted(events, key=lambda event: (event.corrected_at or event.recorded_at, event.event_order, event.id), reverse=True)[:max(0, limit)]

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
        for key in [key for key in self.race_athlete_outcomes if key[0] == race_session_id]:
            self.race_athlete_outcomes.pop(key)
        for event_id in [event.id for event in self.result_events.values() if event.race_session_id == race_session_id]:
            self.result_events.pop(event_id)
        self.race_sessions.pop(race_session_id)
        return True

    def delete_all_timing_data(self) -> bool:
        had_data = bool(self.race_sessions or self.split_events or self.race_session_checkpoints or self.race_athlete_outcomes or self.result_events)
        self.split_events.clear()
        self.race_session_checkpoints.clear()
        self.race_sessions.clear()
        self.race_athlete_outcomes.clear()
        self.result_events.clear()
        return had_data

    def delete_all_race_rosters(self) -> bool:
        had_data = bool(self.race_athletes)
        self.race_athletes.clear()
        return had_data

    def delete_all_application_test_data(self) -> bool:
        had_data = bool(self.meets or self.races or self.athletes or self.race_athletes or self.race_sessions or self.split_events or self.race_session_checkpoints or self.race_athlete_outcomes or self.result_events)
        self.split_events.clear()
        self.race_session_checkpoints.clear()
        self.race_athlete_outcomes.clear()
        self.result_events.clear()
        self.race_sessions.clear()
        self.race_athletes.clear()
        self.races.clear()
        self.meets.clear()
        self.athletes.clear()
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


def _aware_utc(value: datetime) -> datetime:
    """Normalize persisted timestamps for deterministic cross-client ordering."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _split_event_order_key(event: SplitEvent) -> tuple[int, int, datetime, datetime, str]:
    """Prefer authoritative sequence, falling back to legacy timestamps."""
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    if event.event_order > 0:
        return (0, event.event_order, epoch, epoch, event.id)
    return (1, 0, _aware_utc(event.recorded_at), _aware_utc(event.created_at), event.id)


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
        "course_id": race.course_id,
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
        course_id=str(row["course_id"]) if row.get("course_id") else None,
    )


def _course_to_row(course: Course) -> dict[str, Any]:
    return {"id": course.id, "course_name": course.course_name, "location": course.location or None,
            "distance_meters": course.distance_meters, "notes": course.notes or None,
            "created_at": course.created_at.isoformat(), "updated_at": course.updated_at.isoformat()}


def _course_from_row(row: dict[str, Any]) -> Course:
    return Course(id=str(row["id"]), course_name=str(row["course_name"]), location=row.get("location") or "",
                  distance_meters=float(row["distance_meters"]) if row.get("distance_meters") is not None else None,
                  notes=row.get("notes") or "", created_at=_parse_datetime(row.get("created_at")) or utc_now(),
                  updated_at=_parse_datetime(row.get("updated_at")) or utc_now())


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
        "recorded_by": event.recorded_by or None,
        "elapsed_seconds": event.elapsed_seconds,
        "recorded_at": event.recorded_at.isoformat(),
        "event_order": event.event_order,
        "is_deleted": event.is_deleted,
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat(),
        "correction_type": event.correction_type or None,
        "corrected_at": event.corrected_at.isoformat() if event.corrected_at else None,
        "corrected_by": event.corrected_by or None,
        "event_type": event.event_type,
        "target_event_id": event.target_event_id,
        "corrects_event_id": event.corrects_event_id,
        "reason": event.reason or None,
        "client_event_id": event.client_event_id,
        "captured_at": event.captured_at.isoformat() if event.captured_at else None,
        "received_at": event.received_at.isoformat() if event.received_at else None,
        "capture_mode": event.capture_mode,
        "device_id": event.device_id or None,
        "capture_sequence": event.capture_sequence,
        "clock_offset_ms": event.clock_offset_ms,
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
        recorded_by=row.get("recorded_by") or "",
        elapsed_seconds=float(row["elapsed_seconds"]),
        recorded_at=_parse_datetime(row.get("recorded_at")) or utc_now(),
        event_order=int(row.get("event_order") or 0),
        is_deleted=bool(row.get("is_deleted")),
        created_at=_parse_datetime(row.get("created_at")) or utc_now(),
        updated_at=_parse_datetime(row.get("updated_at")) or utc_now(),
        correction_type=row.get("correction_type") or "",
        corrected_at=_parse_datetime(row.get("corrected_at")),
        corrected_by=row.get("corrected_by") or "",
        event_type=row.get("event_type") or "split_recorded",
        target_event_id=str(row["target_event_id"]) if row.get("target_event_id") else None,
        corrects_event_id=str(row["corrects_event_id"]) if row.get("corrects_event_id") else None,
        reason=row.get("reason") or "",
        client_event_id=str(row["client_event_id"]) if row.get("client_event_id") else None,
        captured_at=_parse_datetime(row.get("captured_at")), received_at=_parse_datetime(row.get("received_at")),
        capture_mode=row.get("capture_mode") or "normal", device_id=row.get("device_id") or "",
        capture_sequence=int(row["capture_sequence"]) if row.get("capture_sequence") is not None else None,
        clock_offset_ms=float(row["clock_offset_ms"]) if row.get("clock_offset_ms") is not None else None,
    )


def _race_athlete_outcome_from_row(row: dict[str, Any]) -> RaceAthleteOutcome:
    return RaceAthleteOutcome(
        race_session_id=str(row["race_session_id"]),
        athlete_id=str(row["athlete_id"]),
        status=row.get("status") or "dnf",
        recorded_by=row.get("recorded_by") or "",
        recorded_at=_parse_datetime(row.get("recorded_at")) or utc_now(),
    )


def _result_event_from_row(row: dict[str, Any]) -> ResultEvent:
    raw_splits = row.get("splits") or {}
    return ResultEvent(
        id=str(row["id"]), race_session_id=str(row["race_session_id"]), athlete_id=str(row["athlete_id"]),
        status=str(row["status"]), source=str(row["source"]),
        finish_seconds=float(row["finish_seconds"]) if row.get("finish_seconds") is not None else None,
        splits={int(key): float(value) for key, value in raw_splits.items()}, note=str(row.get("note") or ""),
        supersedes_id=str(row["supersedes_id"]) if row.get("supersedes_id") else None,
        created_by=str(row.get("created_by") or ""), created_at=_parse_datetime(row.get("created_at")) or utc_now(),
    )


def canonical_result_events(events: list[ResultEvent]) -> dict[str, ResultEvent]:
    """Resolve chain heads, independent of database return order."""
    superseded = {event.supersedes_id for event in events if event.supersedes_id}
    heads: dict[str, ResultEvent] = {}
    for event in events:
        if event.id in superseded:
            continue
        previous = heads.get(event.athlete_id)
        if previous is None or (event.created_at, event.id) > (previous.created_at, previous.id):
            heads[event.athlete_id] = event
    return heads


def _validate_result_event(event: ResultEvent) -> None:
    if event.status not in {"finished", "dnf", "dns"}:
        raise RepositoryError("Result status must be Finished, DNF, or DNS.")
    if event.source not in {"live", "manual", "official", "imported"}:
        raise RepositoryError("Result source is not supported.")
    if event.status == "finished" and (event.finish_seconds is None or event.finish_seconds <= 0):
        raise RepositoryError("A positive finish time is required for a finished athlete.")
    if event.status != "finished" and event.finish_seconds is not None:
        raise RepositoryError("DNF and DNS results cannot have a finish time.")
    ordered = [float(value) for _, value in sorted(event.splits.items())]
    if any(value <= 0 for value in ordered) or any(later <= earlier for earlier, later in zip(ordered, ordered[1:])):
        raise RepositoryError("Split times must be positive and increase at every checkpoint.")
    if event.finish_seconds and ordered and ordered[-1] > event.finish_seconds:
        raise RepositoryError("A checkpoint split cannot be later than the finish time.")


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
        "legacy_athlete_id": athlete.athlete_id,
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
        athlete_id=str(row.get("athlete_id") or row.get("legacy_athlete_id") or row["id"]),
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


def _permanent_athlete_to_row(athlete: PermanentAthlete) -> dict[str, Any]:
    return {
        "id": athlete.id, "school_profile_id": athlete.school_profile_id,
        "first_name": athlete.first_name, "last_name": athlete.last_name,
        "preferred_name": athlete.preferred_name or None, "graduation_year": athlete.graduation_year,
        "gender": athlete.gender or None, "team_division": athlete.team_division or None,
        "status": athlete.status, "athlete_number": athlete.athlete_number or None, "notes": athlete.notes or None,
        "created_at": athlete.created_at.isoformat(), "updated_at": athlete.updated_at.isoformat(),
    }


def _permanent_athlete_from_row(row: dict[str, Any]) -> PermanentAthlete:
    return PermanentAthlete(
        id=str(row["id"]), school_profile_id=str(row["school_profile_id"]) if row.get("school_profile_id") else None,
        first_name=str(row["first_name"]), last_name=str(row["last_name"]),
        preferred_name=row.get("preferred_name") or "", graduation_year=int(row["graduation_year"]) if row.get("graduation_year") else None,
        gender=row.get("gender") or "", team_division=row.get("team_division") or "", status=row.get("status") or "active",
        athlete_number=row.get("athlete_number") or "", notes=row.get("notes") or "",
        created_at=_parse_datetime(row.get("created_at")) or utc_now(), updated_at=_parse_datetime(row.get("updated_at")) or utc_now(),
    )


def _school_profile_to_row(profile: SchoolProfile) -> dict[str, Any]:
    """Serialize settings only; image bytes are always stored separately."""
    return {
        "profile_key": "default", "school_name": profile.school_name, "short_name": profile.short_name,
        "program_name": profile.program_name, "mascot": profile.mascot, "city": profile.city,
        "state": profile.state, "app_title": profile.app_title, "primary_color": profile.primary_color,
        "secondary_color": profile.secondary_color, "accent_color": profile.accent_color,
        "text_on_primary": profile.text_on_primary, "logo_path": profile.logo_path,
        "compact_logo_path": profile.compact_logo_path, "header_style": profile.header_style,
        "show_logo_on_dashboard": profile.show_logo_on_dashboard,
        "show_logo_on_timing": profile.show_logo_on_timing,
        "include_branding_on_exports": profile.include_branding_on_exports,
        "updated_at": utc_now().isoformat(),
    }


def _school_profile_from_row(row: dict[str, Any]) -> SchoolProfile:
    defaults = DEFAULT_SCHOOL_PROFILE
    return SchoolProfile(**{
        name: row.get(name) if row.get(name) is not None else getattr(defaults, name)
        for name in SchoolProfile.__dataclass_fields__
    })


def _sponsor_to_row(sponsor: SchoolSponsor) -> dict[str, Any]:
    return {
        "id": sponsor.id, "school_profile_id": sponsor.school_profile_id,
        "name": sponsor.name.strip(), "logo_path": sponsor.logo_path,
        "website_url": sponsor.website_url.strip() or None,
        "display_order": sponsor.display_order, "is_active": sponsor.is_active,
        "created_at": sponsor.created_at.isoformat(), "updated_at": sponsor.updated_at.isoformat(),
    }


def _sponsor_from_row(row: dict[str, Any], logo_url: str = "") -> SchoolSponsor:
    return SchoolSponsor(
        id=str(row["id"]), school_profile_id=str(row["school_profile_id"]),
        name=str(row["name"]), logo_path=str(row["logo_path"]),
        website_url=row.get("website_url") or "", display_order=int(row.get("display_order") or 0),
        is_active=bool(row.get("is_active", True)), logo_url=logo_url,
        created_at=_parse_datetime(row.get("created_at")) or utc_now(),
        updated_at=_parse_datetime(row.get("updated_at")) or utc_now(),
    )


class SupabaseRaceRepository:
    """Supabase-backed repository using the official Python client."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def _execute(self, operation: Any, message: str) -> Any:
        try:
            return operation.execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            detail = str(exc).lower()
            if any(term in detail for term in ("not authorized", "permission denied", "jwt expired", "row-level security")):
                raise RepositoryError("Your coach session has expired or lacks permission. Sign in again.") from exc
            logger.exception("Repository operation failed: %s", message)
            raise RepositoryError(message, diagnostic=_safe_repository_diagnostic(exc)) from exc

    def _single(self, operation: Any, message: str) -> dict[str, Any] | None:
        result = self._execute(operation, message)
        data = getattr(result, "data", None)
        if isinstance(data, list):
            return data[0] if data else None
        return data

    def validate_schema(self) -> None:
        """Run lightweight read checks for tables needed by the active app."""
        checks = (
            ("meets", "id"),
            ("races", "id"),
            ("race_athletes", "athlete_id"),
            ("race_sessions", "id"),
            ("split_events", "id"),
            ("race_session_checkpoints", "id"),
            ("race_session_athlete_outcomes", "race_session_id"),
            ("result_events", "id"),
            ("athletes", "id"),
            ("courses", "id"),
        )
        for table_name, columns in checks:
            message = f"Supabase schema check failed for {table_name}. Apply the required migrations."
            try:
                operation = self.client.table(table_name).select(columns).limit(1)
            except Exception as exc:
                logger.exception("Repository operation failed: %s", message)
                raise RepositoryError(message) from exc
            self._execute(operation, message)

    def validate_public_schema(self) -> None:
        """Validate only anonymous-safe objects needed before coach sign-in."""
        for view_name in (
            "spectator_meets", "spectator_races", "spectator_sessions",
            "spectator_roster", "spectator_checkpoints",
            "spectator_split_events", "spectator_outcomes",
            "spectator_sponsors",
        ):
            try:
                operation = self.client.table(view_name).select("*").limit(1)
            except Exception as exc:
                raise RepositoryError(
                    f"Supabase public schema check failed for {view_name}. Apply migrations through 018."
                ) from exc
            self._execute(
                operation,
                f"Supabase public schema check failed for {view_name}. Apply migrations through 018.",
            )

    def get_school_profile(self) -> SchoolProfile | None:
        row = self._single(self.client.table("school_profiles").select("*").eq("profile_key", "default"), "Could not load school branding.")
        return _school_profile_from_row(row) if row else None

    def save_school_profile(self, profile: SchoolProfile) -> SchoolProfile:
        row = self._single(self.client.table("school_profiles").upsert(_school_profile_to_row(profile), on_conflict="profile_key"), "Could not save school branding.")
        return _school_profile_from_row(row) if row else profile

    def restore_default_school_profile(self) -> SchoolProfile:
        return self.save_school_profile(DEFAULT_SCHOOL_PROFILE)

    def upload_branding_asset(self, object_path: str, content: bytes, content_type: str) -> str:
        try:
            self.client.storage.from_("branding").upload(object_path, content, {"content-type": content_type, "upsert": "true"})
            return object_path
        except Exception as exc:
            logger.exception("Branding asset upload failed")
            raise RepositoryError("Could not upload branding image. Verify the branding bucket and policies.") from exc

    def get_branding_asset_url(self, object_path: str) -> str | None:
        if not object_path:
            return None
        try:
            return self.client.storage.from_("branding").get_public_url(object_path)
        except Exception:
            logger.warning("Branding asset URL unavailable")
            return None

    def _default_school_profile_id(self) -> str:
        row = self._single(self.client.table("school_profiles").select("id").eq("profile_key", "default"), "Could not resolve the school profile.")
        if not row: raise RepositoryError("School profile not found.")
        return str(row["id"])

    def get_school_profile_id(self) -> str:
        return self._default_school_profile_id()

    def list_sponsors(self, school_profile_id=None) -> list[SchoolSponsor]:
        profile_id = school_profile_id or self._default_school_profile_id()
        result = self._execute(
            self.client.table("school_sponsors").select("*").eq("school_profile_id", profile_id).order("display_order").order("name"),
            "Could not list school sponsors.",
        )
        return [
            _sponsor_from_row(row, self.get_branding_asset_url(str(row.get("logo_path") or "")) or "")
            for row in getattr(result, "data", [])
        ]

    def list_active_sponsors(self, school_profile_id=None) -> list[SchoolSponsor]:
        return [item for item in self.list_sponsors(school_profile_id) if item.is_active]

    def get_sponsor(self, sponsor_id: str) -> SchoolSponsor | None:
        row = self._single(self.client.table("school_sponsors").select("*").eq("id", sponsor_id), "Could not load sponsor.")
        return _sponsor_from_row(row, self.get_branding_asset_url(str(row.get("logo_path") or "")) or "") if row else None

    def create_sponsor(self, sponsor: SchoolSponsor) -> SchoolSponsor:
        row = self._single(self.client.table("school_sponsors").insert(_sponsor_to_row(sponsor)), "Could not create sponsor.")
        return _sponsor_from_row(row or _sponsor_to_row(sponsor), self.get_branding_asset_url(sponsor.logo_path) or "")

    def update_sponsor(self, sponsor: SchoolSponsor) -> SchoolSponsor:
        saved = replace(sponsor, updated_at=utc_now())
        row = self._single(self.client.table("school_sponsors").update(_sponsor_to_row(saved)).eq("id", saved.id), "Could not update sponsor.")
        if not row: raise RepositoryError("Sponsor not found.")
        return _sponsor_from_row(row, self.get_branding_asset_url(saved.logo_path) or "")

    def delete_sponsor(self, sponsor_id: str) -> bool:
        result = self._execute(self.client.table("school_sponsors").delete().eq("id", sponsor_id), "Could not delete sponsor.")
        return bool(getattr(result, "data", []))

    def list_athletes(self, *, status=None, graduation_year=None, gender=None, team_division=None, search=None, include_archived=False) -> list[PermanentAthlete]:
        query = self.client.table("athletes").select("*")
        for column, value in (("status", status), ("graduation_year", graduation_year), ("gender", gender), ("team_division", team_division)):
            if value is not None and value != "": query = query.eq(column, value)
        if not include_archived and status is None:
            query = query.neq("status", "archived")
        result = self._execute(query.order("last_name", desc=False).order("first_name", desc=False), "Could not list permanent athletes.")
        athletes = [_permanent_athlete_from_row(row) for row in getattr(result, "data", [])]
        if search:
            term = search.casefold().strip()
            athletes = [item for item in athletes if term in item.display_name.casefold() or term in item.athlete_number.casefold()]
        return athletes

    def get_athlete(self, athlete_id: str) -> PermanentAthlete | None:
        row = self._single(self.client.table("athletes").select("*").eq("id", athlete_id), "Could not load permanent athlete.")
        return _permanent_athlete_from_row(row) if row else None

    def create_athlete(self, athlete: PermanentAthlete) -> PermanentAthlete:
        try: saved = normalize_athlete(athlete)
        except ValueError as exc: raise RepositoryError(str(exc)) from exc
        if saved.school_profile_id is None:
            profile_row = self._single(
                self.client.table("school_profiles").select("id").eq("profile_key", "default"),
                "Could not resolve the default school profile.",
            )
            if profile_row:
                saved = replace(saved, school_profile_id=str(profile_row["id"]))
        row = self._single(self.client.table("athletes").insert(_permanent_athlete_to_row(saved)), "Could not create permanent athlete.")
        return _permanent_athlete_from_row(row) if row else saved

    def update_athlete(self, athlete: PermanentAthlete) -> PermanentAthlete:
        try: saved = replace(normalize_athlete(athlete), updated_at=utc_now())
        except ValueError as exc: raise RepositoryError(str(exc)) from exc
        row = self._single(self.client.table("athletes").update(_permanent_athlete_to_row(saved)).eq("id", saved.id), "Could not update permanent athlete.")
        if row is None and self.get_athlete(saved.id) is None: raise RepositoryError("Athlete not found.")
        return _permanent_athlete_from_row(row) if row else saved

    def set_athlete_status(self, athlete_id: str, status: str) -> PermanentAthlete:
        athlete = self.get_athlete(athlete_id)
        if athlete is None: raise RepositoryError("Athlete not found.")
        return self.update_athlete(replace(athlete, status=status))

    def athlete_has_race_history(self, athlete_id: str) -> bool:
        result = self._execute(
            self.client.table("race_athletes").select("id").eq("athlete_id", athlete_id).limit(1),
            "Could not check athlete race history.",
        )
        return bool(getattr(result, "data", []))

    def archive_athlete(self, athlete_id: str) -> PermanentAthlete:
        return self.set_athlete_status(athlete_id, "archived")

    def restore_athlete(self, athlete_id: str) -> PermanentAthlete:
        athlete = self.get_athlete(athlete_id)
        if athlete is None: raise RepositoryError("Athlete not found.")
        if athlete.status != "archived": raise RepositoryError("Only archived athletes can be restored.")
        return self.set_athlete_status(athlete_id, "active")

    def delete_unused_athlete(self, athlete_id: str) -> bool:
        result = self._execute(
            self.client.rpc("delete_unused_athlete", {"p_athlete_id": athlete_id}),
            "Athlete could not be permanently deleted. It may have race history; archive it instead.",
        )
        data = getattr(result, "data", False)
        deleted = bool(data[0] if isinstance(data, list) and data else data)
        if not deleted: raise RepositoryError("Athlete not found.")
        return True

    def list_race_athlete_ids(self, race_id: str) -> list[str]:
        result = self._execute(self.client.table("race_athletes").select("athlete_id").eq("race_id", race_id).not_.is_("athlete_id", "null"), "Could not list selected permanent athletes.")
        return [str(row["athlete_id"]) for row in getattr(result, "data", []) if row.get("athlete_id")]

    def replace_race_athletes_from_roster(self, race_id: str, athlete_ids: list[str]) -> list[Athlete]:
        if len(athlete_ids) != len(set(athlete_ids)): raise RepositoryError("An athlete can only be selected once per race.")
        existing_rows_result = self._execute(self.client.table("race_athletes").select("*").eq("race_id", race_id), "Could not inspect race roster.")
        existing_rows = {str(row["athlete_id"]): row for row in getattr(existing_rows_result, "data", []) if row.get("athlete_id")}
        removed = set(existing_rows) - set(athlete_ids)
        if removed:
            for session in self.list_race_sessions_for_race(race_id):
                if session.started_at is not None or self.list_all_split_events(session.id):
                    raise RepositoryError("Athletes cannot be removed after timing has started or split events exist.")
        for athlete_id in removed:
            self._execute(self.client.table("race_athletes").delete().eq("race_id", race_id).eq("athlete_id", athlete_id), "Could not remove athlete from race.")
        for temporary_order, row in enumerate(existing_rows.values(), start=1):
            if str(row["athlete_id"]) not in removed:
                self._execute(self.client.table("race_athletes").update({"display_order": -temporary_order}).eq("id", row["id"]), "Could not prepare permanent roster ordering.")
        for index, athlete_id in enumerate(athlete_ids):
            permanent = self.get_athlete(athlete_id)
            if permanent is None: raise RepositoryError("Selected permanent athlete was not found.")
            if permanent.status == "archived" and athlete_id not in existing_rows:
                raise RepositoryError("Archived athletes cannot be added to a new race roster. Restore the athlete first.")
            if athlete_id in existing_rows:
                self._execute(self.client.table("race_athletes").update({"display_order": index}).eq("race_id", race_id).eq("athlete_id", athlete_id), "Could not reorder race athlete.")
            else:
                snapshot = Athlete(name=permanent.display_name, athlete_id=permanent.id, gender=permanent.gender, team=permanent.team_division, display_order=index)
                row = _athlete_to_row(race_id, snapshot, index)
                row["athlete_id"], row["legacy_athlete_id"] = permanent.id, None
                self._execute(self.client.table("race_athletes").insert(row), "Could not select permanent athlete for race.")
        return self.list_race_athletes(race_id, include_inactive=True)

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

    def list_courses(self) -> list[Course]:
        result = self._execute(self.client.table("courses").select("*").order("course_name"), "Could not list courses.")
        return [_course_from_row(row) for row in getattr(result, "data", [])]

    def create_course(self, course: Course) -> Course:
        if not course.course_name.strip(): raise RepositoryError("Course name is required.")
        saved = replace(course, course_name=course.course_name.strip(), updated_at=utc_now())
        row = self._single(self.client.table("courses").insert(_course_to_row(saved)), "Could not create course.")
        return _course_from_row(row or _course_to_row(saved))

    def update_course(self, course: Course) -> Course:
        saved = replace(course, course_name=course.course_name.strip(), updated_at=utc_now())
        row = self._single(self.client.table("courses").update(_course_to_row(saved)).eq("id", saved.id), "Could not update course.")
        if not row: raise RepositoryError("Course not found.")
        return _course_from_row(row)

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
        result = self._execute(self.client.table("race_athletes").select("*").eq("race_id", race_id), "Could not inspect race roster.")
        existing = {str(row.get("athlete_id") or row.get("legacy_athlete_id") or row["id"]): row for row in getattr(result, "data", [])}
        removed = set(existing) - {athlete.athlete_id for athlete in athletes}
        if removed and any(session.started_at or self.list_all_split_events(session.id) for session in self.list_race_sessions_for_race(race_id)):
            raise RepositoryError("Athletes cannot be removed after timing has started or split events exist.")
        for athlete_id in removed:
            self._execute(self.client.table("race_athletes").delete().eq("id", existing[athlete_id]["id"]), "Could not remove race athlete.")
        for temporary_order, prior in enumerate(existing.values(), start=1):
            identity = str(prior.get("athlete_id") or prior.get("legacy_athlete_id") or prior["id"])
            if identity not in removed:
                self._execute(self.client.table("race_athletes").update({"display_order": -temporary_order}).eq("id", prior["id"]), "Could not prepare race roster ordering.")
        for index, athlete in enumerate(athletes):
            row = _athlete_to_row(race_id, athlete, index)
            prior = existing.get(athlete.athlete_id)
            if prior:
                row["athlete_id"] = prior.get("athlete_id")
                row["legacy_athlete_id"] = prior.get("legacy_athlete_id")
                self._execute(self.client.table("race_athletes").update(row).eq("id", prior["id"]), "Could not update race roster.")
            else:
                permanent = self.get_athlete(athlete.athlete_id)
                if permanent:
                    row["athlete_id"], row["legacy_athlete_id"] = permanent.id, None
                self._execute(self.client.table("race_athletes").insert(row), "Could not save race roster.")
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

    def get_or_create_active_race_session(self, race_id: str, checkpoints: list[Checkpoint]) -> RaceSession:
        """Use the database-serialized start operation for one race."""
        if not checkpoints:
            raise RepositoryError("At least one checkpoint is required to start a race session.")
        result = self._execute(
            self.client.rpc(
                "get_or_create_active_race_session",
                {
                    "p_race_id": race_id,
                    "p_checkpoints": [_session_checkpoint_rpc_payload(checkpoint) for checkpoint in checkpoints],
                },
            ),
            "Could not get or create the active race session.",
        )
        data = getattr(result, "data", [])
        if not data:
            raise RepositoryError("Could not get or create the active race session.")
        row = data[0] if isinstance(data, list) else data
        return _race_session_from_row(row)

    def get_race_session(self, race_session_id: str) -> RaceSession | None:
        row = self._single(self.client.table("race_sessions").select("*").eq("id", race_session_id), "Could not load race session.")
        return _race_session_from_row(row) if row else None

    def start_race_session(self, race_session_id: str, started_at: datetime) -> RaceSession:
        """Conditionally start one ready row without overwriting another client's start."""
        saved_at = utc_now()
        result = self._execute(
            self.client.table("race_sessions")
            .update({"status": "running", "started_at": started_at.isoformat(), "updated_at": saved_at.isoformat()})
            .eq("id", race_session_id)
            .eq("status", "ready")
            .is_("started_at", "null"),
            "Could not start race session.",
        )
        rows = getattr(result, "data", [])
        if rows:
            return _race_session_from_row(rows[0])
        current = self.get_race_session(race_session_id)
        if current is not None and current.status in {"running", "paused"} and current.started_at is not None:
            return current
        if current is None:
            raise RepositoryError("Race session not found.")
        raise RepositoryError("Race session cannot be started from its current state.")

    def get_active_or_latest_race_session_for_race(self, race_id: str) -> RaceSession | None:
        active_result = self._execute(self.client.table("race_sessions").select("*").eq("race_id", race_id).in_("status", ["ready", "running", "paused"]).order("created_at", desc=False), "Could not load active race session.")
        active_rows = getattr(active_result, "data", [])
        if active_rows:
            return _race_session_from_row(active_rows[-1])
        all_sessions = self.list_race_sessions_for_race(race_id)
        return all_sessions[-1] if all_sessions else None

    def update_race_session(self, session: RaceSession) -> RaceSession:
        saved = replace(session, updated_at=utc_now())
        row = self._single(self.client.table("race_sessions").update(_race_session_to_row(saved)).eq("id", saved.id), "Could not update race session.")
        return _race_session_from_row(row or _race_session_to_row(saved))

    def transition_race_session(self, race_session_id: str, action: str) -> RaceSession:
        """Request one locked, server-authoritative lifecycle transition."""
        try:
            result = self.client.rpc(
                "transition_race_session",
                {"p_session_id": race_session_id, "p_action": action},
            ).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            detail = str(exc).lower()
            if any(term in detail for term in ("invalid race session transition", "unknown race session action", "race session not found")):
                raise RepositoryError(str(exc)) from exc
            logger.exception("Repository operation failed: Could not transition race session.")
            raise RepositoryError("Could not transition race session.") from exc
        rows = getattr(result, "data", [])
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not row:
            raise RepositoryError("Could not transition race session.")
        return _race_session_from_row(row)

    def complete_race_timing(self, race_session_id: str, finish_checkpoint_number: int | None = None) -> RaceSession:
        try:
            function_name = (
                "complete_race_timing_at_finish"
                if finish_checkpoint_number is not None
                else "complete_race_timing"
            )
            parameters = {"p_session_id": race_session_id}
            if finish_checkpoint_number is not None:
                parameters["p_checkpoint_number"] = finish_checkpoint_number
            result = self.client.rpc(
                function_name, parameters
            ).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            detail = str(exc).lower()
            if any(term in detail for term in ("running or paused", "finish line", "not found")):
                raise RepositoryError(str(exc)) from exc
            logger.exception("Repository operation failed: Could not end race timing.")
            raise RepositoryError("Could not end race timing.") from exc
        rows = getattr(result, "data", []) or []
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not row:
            raise RepositoryError("Could not end race timing.")
        return _race_session_from_row(row)

    def finalize_race_session(self, race_session_id: str) -> RaceSession:
        try:
            result = self.client.rpc("finalize_race_session", {"p_session_id": race_session_id}).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            detail = str(exc).lower()
            if any(term in detail for term in ("resolve every", "cannot be finished", "not found")):
                raise RepositoryError(str(exc)) from exc
            logger.exception("Repository operation failed: Could not finish race session.")
            raise RepositoryError("Could not finish the race.") from exc
        rows = getattr(result, "data", [])
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not row: raise RepositoryError("Could not finish the race.")
        return _race_session_from_row(row)

    def reopen_race_session(self, race_session_id: str) -> RaceSession:
        try:
            result = self.client.rpc("reopen_race_session", {"p_session_id": race_session_id}).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            detail = str(exc).lower()
            if any(term in detail for term in ("only a completed", "not found")):
                raise RepositoryError(str(exc)) from exc
            logger.exception("Repository operation failed: Could not reopen race session.")
            raise RepositoryError("Could not reopen the race.") from exc
        rows = getattr(result, "data", [])
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not row: raise RepositoryError("Could not reopen the race.")
        return _race_session_from_row(row)

    def list_race_athlete_outcomes(self, race_session_id: str) -> list[RaceAthleteOutcome]:
        result = self._execute(
            self.client.table("race_session_athlete_outcomes").select("*").eq("race_session_id", race_session_id).order("recorded_at", desc=False),
            "Could not load race athlete outcomes.",
        )
        return [_race_athlete_outcome_from_row(row) for row in getattr(result, "data", [])]

    def set_race_athlete_dnf(self, race_session_id: str, athlete_id: str, recorded_by: str) -> RaceAthleteOutcome:
        try:
            result = self.client.rpc("set_race_athlete_dnf", {
                "p_session_id": race_session_id, "p_athlete_id": athlete_id,
                "p_recorded_by": recorded_by or None,
            }).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            raise RepositoryError(str(exc)) from exc
        rows = getattr(result, "data", [])
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not row: raise RepositoryError("Could not mark athlete DNF.")
        return _race_athlete_outcome_from_row(row)

    def clear_race_athlete_dnf(self, race_session_id: str, athlete_id: str) -> bool:
        try:
            result = self.client.rpc("clear_race_athlete_dnf", {
                "p_session_id": race_session_id, "p_athlete_id": athlete_id,
            }).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            raise RepositoryError(str(exc)) from exc
        data = getattr(result, "data", False)
        return bool(data[0] if isinstance(data, list) and data else data)

    def list_result_events(self, race_session_id: str, athlete_id: str | None = None) -> list[ResultEvent]:
        query = self.client.table("result_events").select("*").eq("race_session_id", race_session_id)
        if athlete_id is not None:
            query = query.eq("athlete_id", athlete_id)
        try:
            result = query.order("created_at", desc=False).execute()
        except Exception:
            result = self._execute(self.client.rpc("get_public_result_events", {"p_session_id": race_session_id}), "Could not load current results.")
        return [_result_event_from_row(row) for row in (getattr(result, "data", []) or [])]

    def save_post_race_result(self, event: ResultEvent) -> ResultEvent:
        _validate_result_event(event)
        try:
            result = self.client.rpc("append_post_race_result", {
                "p_id": event.id, "p_session_id": event.race_session_id, "p_athlete_id": event.athlete_id,
                "p_status": event.status, "p_finish_seconds": event.finish_seconds, "p_source": event.source,
                "p_splits": {str(key): value for key, value in event.splits.items()}, "p_note": event.note or None,
                "p_supersedes_id": event.supersedes_id,
            }).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            raise RepositoryError(str(exc)) from exc
        rows = getattr(result, "data", []) or []
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not row:
            raise RepositoryError("Could not save the historical result.")
        return _result_event_from_row(row)

    def list_race_sessions_for_race(self, race_id: str) -> list[RaceSession]:
        result = self._execute(self.client.table("race_sessions").select("*").eq("race_id", race_id).order("created_at", desc=False), "Could not list race sessions.")
        return [_race_session_from_row(row) for row in getattr(result, "data", [])]

    def list_race_sessions_for_races(self, race_ids: list[str]) -> list[RaceSession]:
        if not race_ids:
            return []
        result = self._execute(
            self.client.table("race_sessions").select("*").in_("race_id", race_ids).order("created_at", desc=False),
            "Could not list race sessions for the race-day dashboard.",
        )
        return [_race_session_from_row(row) for row in getattr(result, "data", [])]

    def count_race_athletes_for_races(self, race_ids: list[str]) -> dict[str, int]:
        counts = {race_id: 0 for race_id in race_ids}
        if not race_ids:
            return counts
        result = self._execute(
            self.client.table("race_athletes").select("race_id").in_("race_id", race_ids).eq("active", True),
            "Could not count race athletes for the race-day dashboard.",
        )
        for row in getattr(result, "data", []):
            race_id = str(row["race_id"])
            if race_id in counts:
                counts[race_id] += 1
        return counts

    def create_split_event(self, event: SplitEvent) -> SplitEvent:
        event_row = _split_event_to_row(event)
        try:
            result = self.client.rpc("record_shared_split", {"p_event": event_row}).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            detail = str(exc).lower()
            if "duplicate" in detail or "already" in detail or "23505" in detail:
                raise RepositoryError("That athlete already has an active split at this checkpoint.") from exc
            if any(term in detail for term in ("not running", "invalid athlete", "checkpoint progression", "no remaining checkpoint")):
                raise RepositoryError(str(exc)) from exc
            logger.exception("Repository operation failed: Could not create split event.")
            raise RepositoryError("Could not create split event.") from exc
        rows = getattr(result, "data", [])
        row = rows[0] if isinstance(rows, list) and rows else rows
        return _split_event_from_row(row or event_row)

    def record_shared_split(self, race_session_id: str, athlete_id: str, checkpoint_number: int, recorded_by: str, request_id: str) -> SplitEvent:
        """Record one split without accepting client-authoritative timing fields."""
        payload = {
            "id": request_id,
            "race_session_id": race_session_id,
            "athlete_id": athlete_id,
            "checkpoint_number": checkpoint_number,
            "recorded_by": recorded_by or None,
        }
        try:
            result = self.client.rpc("record_shared_split", {"p_event": payload}).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            detail = str(exc).lower()
            if "duplicate" in detail or "already" in detail or "23505" in detail:
                raise RepositoryError("That athlete already has an active split at this checkpoint.") from exc
            if any(term in detail for term in ("not running", "invalid athlete", "no remaining checkpoint", "checkpoint progression", "different action")):
                raise RepositoryError(str(exc)) from exc
            logger.exception("Repository operation failed: Could not record shared split.")
            raise RepositoryError("Could not record shared split.") from exc
        rows = getattr(result, "data", [])
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not row:
            raise RepositoryError("Could not record shared split.")
        return _split_event_from_row(row)

    def record_pack_split_events(self, race_session_id: str, events: list[dict[str, Any]], recorded_by: str) -> list[SplitEvent]:
        if not events: return []
        try:
            result = self.client.rpc("record_pack_split_events", {"p_session_id": race_session_id, "p_events": events, "p_recorded_by": recorded_by or None}).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            raise RepositoryError("Pack events remain safely queued on this device.", diagnostic=_safe_repository_diagnostic(exc)) from exc
        return [_split_event_from_row(row) for row in (getattr(result, "data", []) or [])]

    def list_active_split_events(self, race_session_id: str) -> list[SplitEvent]:
        events = self.list_all_split_events(race_session_id)
        inactive = {event.target_event_id for event in events if event.event_type == "split_voided" and event.target_event_id}
        return [event for event in events if event.event_type not in {"split_voided", "pack_conflict"} and not event.is_deleted and event.id not in inactive]

    def list_all_split_events(self, race_session_id: str) -> list[SplitEvent]:
        result = self._execute(self.client.table("split_events").select("*").eq("race_session_id", race_session_id).order("event_order", desc=False), "Could not list split events.")
        return sorted(
            [_split_event_from_row(row) for row in getattr(result, "data", [])],
            key=_split_event_order_key,
        )

    def soft_delete_split_event(self, split_event_id: str) -> SplitEvent:
        updated_at = utc_now().isoformat()
        row = self._single(self.client.table("split_events").update({"is_deleted": True, "updated_at": updated_at}).eq("id", split_event_id), "Could not undo split event.")
        if row is None:
            raise RepositoryError("Split event not found.")
        return _split_event_from_row(row)

    def invalidate_split_event(self, split_event_id: str, race_session_id: str, athlete_id: str, checkpoint_number: int, corrected_by: str, *, require_latest: bool = False) -> SplitEvent:
        try:
            result = self.client.rpc("invalidate_split_event", {
                "p_event_id": split_event_id,
                "p_session_id": race_session_id,
                "p_athlete_id": athlete_id,
                "p_checkpoint_number": checkpoint_number,
                "p_corrected_by": corrected_by or None,
                "p_require_latest": require_latest,
            }).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            detail = str(exc).lower()
            if any(term in detail for term in ("already corrected", "no longer matches", "not found", "newer split")):
                raise RepositoryError(str(exc)) from exc
            logger.exception("Repository operation failed: Could not invalidate split event.")
            raise RepositoryError("Could not correct the selected split.") from exc
        rows = getattr(result, "data", [])
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not row: raise RepositoryError("The selected split was not corrected.")
        return _split_event_from_row(row)

    def record_manual_split(self, race_session_id: str, athlete_id: str, checkpoint_number: int, elapsed_seconds: float, recorded_by: str, request_id: str) -> SplitEvent:
        payload = {
            "id": request_id,
            "race_session_id": race_session_id,
            "athlete_id": athlete_id,
            "checkpoint_number": checkpoint_number,
            "elapsed_seconds": elapsed_seconds,
            "recorded_by": recorded_by or None,
        }
        try:
            result = self.client.rpc("record_manual_split", {"p_event": payload}).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            detail = str(exc).lower()
            if any(term in detail for term in ("next missing", "surrounding", "not running", "not paused", "invalid athlete", "request id")):
                raise RepositoryError(str(exc)) from exc
            logger.exception("Repository operation failed: Could not record manual split.")
            raise RepositoryError("Could not add the missed split.") from exc
        rows = getattr(result, "data", [])
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not row: raise RepositoryError("Could not add the missed split.")
        return _split_event_from_row(row)

    def list_recent_split_events(self, race_session_id: str, *, limit: int = 10) -> list[SplitEvent]:
        result = self._execute(
            self.client.table("split_events").select("*").eq("race_session_id", race_session_id),
            "Could not load recent timing activity.",
        )
        events = [_split_event_from_row(row) for row in getattr(result, "data", [])]
        return sorted(events, key=lambda event: (event.corrected_at or event.recorded_at, event.event_order, event.id), reverse=True)[:max(0, limit)]

    def correct_split_athlete(self, split_event_id: str, race_session_id: str, athlete_id: str, checkpoint_number: int, new_athlete_id: str, corrected_by: str, request_id: str) -> list[SplitEvent]:
        try:
            result = self.client.rpc("correct_split_athlete", {"p_event_id": split_event_id, "p_session_id": race_session_id, "p_athlete_id": athlete_id, "p_checkpoint_number": checkpoint_number, "p_new_athlete_id": new_athlete_id, "p_corrected_by": corrected_by or None, "p_request_id": request_id}).execute()
        except Exception as exc:
            _raise_authorization_error(exc)
            raise RepositoryError(str(exc)) from exc
        rows = getattr(result, "data", []) or []
        if len(rows) != 2: raise RepositoryError("The split reassignment was not completed.")
        return [_split_event_from_row(row) for row in rows]

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
        athletes = self._execute(self.client.table("athletes").select("id"), "Could not inspect permanent athletes.")
        had_data = bool(getattr(meets, "data", []) or getattr(sessions, "data", []) or getattr(rosters, "data", []) or getattr(athletes, "data", []))
        self._execute(self.client.table("race_sessions").delete().neq("id", DELETE_ALL_FILTER_SENTINEL), "Could not delete timing sessions.")
        self._execute(self.client.table("meets").delete().neq("id", DELETE_ALL_FILTER_SENTINEL), "Could not delete meets and races.")
        self._execute(self.client.table("athletes").delete().neq("id", DELETE_ALL_FILTER_SENTINEL), "Could not delete permanent athletes.")
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
        repository.validate_public_schema()
    except RepositoryError as exc:
        return RepositoryFactoryResult(repository=None, storage_label="Supabase unavailable", is_temporary=False, message="Supabase is configured but initialization failed.", error=str(exc))
    # Anonymous startup never probes or seeds protected coach tables. All
    # mutations run only after Supabase Auth establishes an authorized JWT.
    return RepositoryFactoryResult(repository=repository, storage_label="Supabase", is_temporary=False, message="Meet data is stored in Supabase.")
