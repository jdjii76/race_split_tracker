"""Read-only spectator projection assembled from authoritative persisted data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from split_tracker.formatting import format_duration
from split_tracker.models import Athlete, Checkpoint
from split_tracker.projection import ProjectedRaceState, ordered_race_board_athletes, project_race_state
from split_tracker.repository import Meet, Race, RaceAthleteOutcome, RaceSession, RaceSessionCheckpoint, SplitEvent
from split_tracker.results import reconstruct_results


class SpectatorReadRepository(Protocol):
    """Only the read operations available to the spectator data path."""

    def get_race(self, race_id: str) -> Race | None: ...
    def get_meet(self, meet_id: str) -> Meet | None: ...
    def get_race_session(self, race_session_id: str) -> RaceSession | None: ...
    def get_active_or_latest_race_session_for_race(self, race_id: str) -> RaceSession | None: ...
    def list_race_athletes(self, race_id: str, *, include_inactive: bool = False) -> list[Athlete]: ...
    def list_race_session_checkpoints(self, race_session_id: str): ...
    def list_active_split_events(self, race_session_id: str) -> list[SplitEvent]: ...
    def list_race_athlete_outcomes(self, race_session_id: str) -> list[RaceAthleteOutcome]: ...


class ReadOnlySpectatorRepository:
    """Capability-limited adapter that intentionally exposes no mutation API."""

    def __init__(self, repository: object) -> None:
        self.__repository = repository

    def get_race(self, race_id: str):
        return self.__repository.get_race(race_id)

    def get_meet(self, meet_id: str):
        return self.__repository.get_meet(meet_id)

    def get_race_session(self, race_session_id: str):
        return self.__repository.get_race_session(race_session_id)

    def get_active_or_latest_race_session_for_race(self, race_id: str):
        return self.__repository.get_active_or_latest_race_session_for_race(race_id)

    def list_race_athletes(self, race_id: str, *, include_inactive: bool = False):
        return self.__repository.list_race_athletes(race_id, include_inactive=include_inactive)

    def list_race_session_checkpoints(self, race_session_id: str):
        return self.__repository.list_race_session_checkpoints(race_session_id)

    def list_active_split_events(self, race_session_id: str):
        return self.__repository.list_active_split_events(race_session_id)

    def list_race_athlete_outcomes(self, race_session_id: str):
        return self.__repository.list_race_athlete_outcomes(race_session_id)


class PublicSupabaseSpectatorRepository:
    """Read public privacy views through an anonymous or authenticated client."""

    def __init__(self, client: object) -> None:
        self.__client = client

    def _rows(self, query) -> list[dict]:
        return list(getattr(query.execute(), "data", None) or [])

    def get_race(self, race_id: str):
        rows = self._rows(self.__client.table("spectator_races").select("*").eq("id", race_id).limit(1))
        return _public_race(rows[0]) if rows else None

    def get_meet(self, meet_id: str):
        rows = self._rows(self.__client.table("spectator_meets").select("*").eq("id", meet_id).limit(1))
        return Meet(id=str(rows[0]["id"]), name=str(rows[0]["name"]), status=rows[0].get("status") or "draft") if rows else None

    def get_race_session(self, race_session_id: str):
        rows = self._rows(self.__client.table("spectator_sessions").select("*").eq("id", race_session_id).limit(1))
        return _public_session(rows[0]) if rows else None

    def get_active_or_latest_race_session_for_race(self, race_id: str):
        rows = self._rows(self.__client.table("spectator_sessions").select("*").eq("race_id", race_id).order("created_at", desc=True))
        active = next((row for row in rows if row.get("status") in {"ready", "running", "paused"}), None)
        return _public_session(active or rows[0]) if rows else None

    def list_race_athletes(self, race_id: str, *, include_inactive: bool = False):
        query = self.__client.table("spectator_roster").select("*").eq("race_id", race_id).order("display_order")
        if not include_inactive:
            query = query.eq("active", True)
        return [Athlete(name=str(row["name"]), athlete_id=str(row["athlete_id"]), team=row.get("team") or "", display_order=int(row.get("display_order") or 0)) for row in self._rows(query)]

    def list_race_session_checkpoints(self, race_session_id: str):
        rows = self._rows(self.__client.table("spectator_checkpoints").select("*").eq("race_session_id", race_session_id).order("checkpoint_sequence"))
        return [RaceSessionCheckpoint(race_session_id=race_session_id, checkpoint_sequence=int(row["checkpoint_sequence"]), label=str(row["label"]), distance_meters=float(row["distance_meters"]), is_finish=bool(row.get("is_finish"))) for row in rows]

    def list_active_split_events(self, race_session_id: str):
        rows = self._rows(self.__client.table("spectator_split_events").select("*").eq("race_session_id", race_session_id).order("event_order"))
        return [SplitEvent(race_session_id=race_session_id, athlete_id=str(row["athlete_id"]), athlete_name=row.get("athlete_name") or "", checkpoint_number=int(row["checkpoint_number"]), checkpoint_label=row.get("checkpoint_label") or "", elapsed_seconds=float(row["elapsed_seconds"]), event_order=int(row.get("event_order") or 0), id=str(row["id"]), correction_type=row.get("correction_type") or "") for row in rows]

    def list_race_athlete_outcomes(self, race_session_id: str):
        rows = self._rows(self.__client.table("spectator_outcomes").select("*").eq("race_session_id", race_session_id))
        return [RaceAthleteOutcome(race_session_id=race_session_id, athlete_id=str(row["athlete_id"]), status=row.get("status") or "dnf") for row in rows]


def spectator_repository(repository: object) -> SpectatorReadRepository:
    """Choose public Supabase views without changing the in-memory test adapter."""
    client = getattr(repository, "client", None)
    return PublicSupabaseSpectatorRepository(client) if client is not None else ReadOnlySpectatorRepository(repository)


def _public_race(row: dict) -> Race:
    return Race(id=str(row["id"]), meet_id=str(row["meet_id"]), name=str(row["name"]), distance_meters=float(row["distance_meters"]), race_category=row.get("race_category") or "", course_type=row.get("course_type") or "Cross Country", checkpoint_mode=row.get("checkpoint_mode") or "Standard laps", status=row.get("status") or "draft", display_order=int(row.get("display_order") or 0))


def _public_session(row: dict) -> RaceSession:
    return RaceSession(id=str(row["id"]), race_id=str(row["race_id"]), status=row.get("status") or "ready", elapsed_offset_seconds=float(row.get("elapsed_offset_seconds") or 0))


@dataclass(frozen=True)
class SpectatorAthleteRow:
    name: str
    team: str
    latest_checkpoint: str
    cumulative_time: str
    next_checkpoint: str
    status: str


@dataclass(frozen=True)
class SpectatorRaceView:
    race: Race
    meet: Meet | None
    session: RaceSession | None
    status: str
    athlete_rows: tuple[SpectatorAthleteRow, ...] = ()
    final_rows: tuple[dict[str, object], ...] = ()


def spectator_url(race_id: str, session_id: str | None = None) -> str:
    query = f"spectator_race={race_id}"
    if session_id:
        query += f"&spectator_session={session_id}"
    return f"/live-race?{query}"


def spectator_status(session: RaceSession | None) -> str:
    if session is None or session.status == "ready":
        return "Not Started"
    return {"running": "Running", "paused": "Paused", "completed": "Finished", "cancelled": "Finished"}.get(session.status, "Not Started")


def load_spectator_race(
    repository: SpectatorReadRepository,
    *,
    race_id: str | None,
    session_id: str | None = None,
) -> SpectatorRaceView | None:
    """Resolve stable IDs and load only one race's read-only authoritative state."""
    session = repository.get_race_session(session_id) if session_id else None
    if session_id and session is None:
        return None
    resolved_race_id = race_id or (session.race_id if session else None)
    if not resolved_race_id:
        return None
    race = repository.get_race(resolved_race_id)
    if race is None or (session is not None and session.race_id != race.id):
        return None
    if session is None:
        session = repository.get_active_or_latest_race_session_for_race(race.id)
    meet = repository.get_meet(race.meet_id)
    if session is None:
        return SpectatorRaceView(race, meet, None, "Not Started")

    athletes = repository.list_race_athletes(race.id)
    snapshots = repository.list_race_session_checkpoints(session.id)
    checkpoints = [Checkpoint(item.checkpoint_sequence, item.label, item.distance_meters, item.is_finish) for item in snapshots]
    events = repository.list_active_split_events(session.id)
    outcomes = repository.list_race_athlete_outcomes(session.id)
    dnf_ids = {item.athlete_id for item in outcomes if item.status == "dnf"}
    projection = project_race_state(session, athletes, checkpoints, events, dnf_ids)
    rows = _spectator_athlete_rows(projection)
    final_rows: list[dict[str, object]] = []
    if session.status == "completed":
        final_rows = reconstruct_results(
            meet_name=meet.name if meet else "", race_name=race.name, session=session,
            athletes=athletes, checkpoints=checkpoints, race_distance_meters=race.distance_meters,
            events=events, outcomes=outcomes,
        )
    return SpectatorRaceView(race, meet, session, spectator_status(session), tuple(rows), tuple(final_rows))


def _spectator_athlete_rows(projection: ProjectedRaceState) -> list[SpectatorAthleteRow]:
    has_progress = any(item.completed_split_count for item in projection.athletes)
    ordered = list(ordered_race_board_athletes(projection)) if has_progress else list(projection.athletes)
    ordered.sort(key=lambda item: item.outcome_status == "dnf")
    rows = []
    for item in ordered:
        latest = item.splits[-1] if item.splits else None
        status = "DNF" if item.outcome_status == "dnf" else ("Finished" if item.finished else "In Progress" if latest else "Not Started")
        rows.append(SpectatorAthleteRow(
            name=item.athlete.name,
            team=item.athlete.team,
            latest_checkpoint=latest.checkpoint_label if latest else "No split yet",
            cumulative_time=format_duration(latest.cumulative_time_seconds if latest else None),
            next_checkpoint=item.next_checkpoint.label if item.next_checkpoint and item.outcome_status != "dnf" else "—",
            status=status,
        ))
    return rows
