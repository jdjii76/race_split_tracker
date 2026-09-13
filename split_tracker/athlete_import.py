"""Pure CSV parsing plus repository-backed permanent-roster import."""
from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO

import pandas as pd

from split_tracker.athletes import normalize_athlete
from split_tracker.models import PermanentAthlete

CSV_COLUMNS = (
    "first_name", "last_name", "preferred_name", "graduation_year", "gender",
    "team_division", "athlete_number", "status", "notes",
)
DUPLICATE_POLICIES = {"skip", "update", "create"}


@dataclass(frozen=True)
class AthleteImportRow:
    row_number: int
    athlete: PermanentAthlete | None
    errors: tuple[str, ...] = ()
    duplicate_athlete_id: str | None = None
    duplicate_reason: str = ""


@dataclass(frozen=True)
class AthleteImportSummary:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0


def csv_template_bytes() -> bytes:
    return (",".join(CSV_COLUMNS) + "\n").encode("utf-8")


def _clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _graduation_year(value: object) -> int | None:
    text = _clean(value)
    if not text:
        return None
    number = float(text)
    if not number.is_integer():
        raise ValueError("graduation_year must be a whole year.")
    return int(number)


def find_duplicate(athlete: PermanentAthlete, existing: list[PermanentAthlete]) -> tuple[str | None, str]:
    """Find an unambiguous athlete-number match, otherwise flag identity review."""
    if athlete.athlete_number:
        matches = [item for item in existing if item.athlete_number.casefold() == athlete.athlete_number.casefold()]
        if len(matches) == 1:
            return matches[0].id, "Athlete number already exists"
    matches = [
        item for item in existing
        if item.first_name.casefold() == athlete.first_name.casefold()
        and item.last_name.casefold() == athlete.last_name.casefold()
        and item.graduation_year == athlete.graduation_year
    ]
    if len(matches) == 1:
        return matches[0].id, "Name and graduation year already exist"
    return None, ""


def parse_athlete_csv(data: bytes, existing: list[PermanentAthlete] | None = None) -> list[AthleteImportRow]:
    """Parse and validate without writing; malformed rows remain previewable."""
    existing = existing or []
    try:
        frame = pd.read_csv(BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        return [AthleteImportRow(0, None, (f"CSV could not be parsed: {exc}",))]
    missing = [column for column in ("first_name", "last_name") if column not in frame.columns]
    if missing:
        return [AthleteImportRow(0, None, (f"Missing required column(s): {', '.join(missing)}.",))]
    rows: list[AthleteImportRow] = []
    seen_numbers: set[str] = set()
    seen_identities: set[tuple[str, str, int | None]] = set()
    for index, record in frame.iterrows():
        errors: list[str] = []
        imported_number = _clean(record.get("athlete_number"))
        number_key = imported_number.casefold()
        if number_key and number_key in seen_numbers:
            errors.append("athlete_number is duplicated within this CSV.")
        if number_key:
            seen_numbers.add(number_key)
        try:
            athlete = normalize_athlete(PermanentAthlete(
                first_name=_clean(record.get("first_name")), last_name=_clean(record.get("last_name")),
                preferred_name=_clean(record.get("preferred_name")), graduation_year=_graduation_year(record.get("graduation_year")),
                gender=_clean(record.get("gender")), team_division=_clean(record.get("team_division")),
                athlete_number=imported_number, status=_clean(record.get("status")) or "active",
                notes=_clean(record.get("notes")),
            ))
        except (ValueError, TypeError) as exc:
            athlete = None
            errors.append(str(exc))
        if athlete:
            identity = (athlete.first_name.casefold(), athlete.last_name.casefold(), athlete.graduation_year)
            if identity in seen_identities:
                errors.append("Name and graduation year are duplicated within this CSV.")
            seen_identities.add(identity)
        duplicate_id, reason = find_duplicate(athlete, existing) if athlete else (None, "")
        rows.append(AthleteImportRow(index + 2, athlete, tuple(errors), duplicate_id, reason))
    return rows


def import_athlete_rows(repository, rows: list[AthleteImportRow], duplicate_policy: str) -> AthleteImportSummary:
    """Persist previously validated rows only after explicit UI confirmation."""
    if duplicate_policy not in DUPLICATE_POLICIES:
        raise ValueError("Duplicate policy is invalid.")
    created = updated = skipped = failed = 0
    for row in rows:
        if row.errors or row.athlete is None:
            failed += 1
            continue
        try:
            if row.duplicate_athlete_id and duplicate_policy == "skip":
                skipped += 1
            elif row.duplicate_athlete_id and duplicate_policy == "update":
                current = repository.get_athlete(row.duplicate_athlete_id)
                if current is None:
                    failed += 1
                    continue
                repository.update_athlete(replace(
                    row.athlete, id=current.id, school_profile_id=current.school_profile_id,
                    created_at=current.created_at,
                ))
                updated += 1
            else:
                repository.create_athlete(row.athlete)
                created += 1
        except Exception:
            failed += 1
    return AthleteImportSummary(created, updated, skipped, failed)
