"""Pure permanent-athlete validation and school-grade helpers."""
from __future__ import annotations
from dataclasses import replace
from split_tracker.models import PermanentAthlete

ATHLETE_STATUSES = {"active", "inactive", "injured", "graduated", "archived"}


def grade_from_graduation_year(graduation_year: int | None, school_year_end: int) -> str:
    if graduation_year is None:
        return "—"
    grade = 12 - (graduation_year - school_year_end)
    if grade > 12:
        return "Graduated"
    if grade < 9:
        return "Future student"
    return {9: "9th", 10: "10th", 11: "11th", 12: "12th"}[grade]


def normalize_athlete(athlete: PermanentAthlete) -> PermanentAthlete:
    normalized = replace(
        athlete,
        first_name=" ".join(athlete.first_name.split()), last_name=" ".join(athlete.last_name.split()),
        preferred_name=" ".join(athlete.preferred_name.split()), gender=athlete.gender.strip(),
        team_division=athlete.team_division.strip(), athlete_number=athlete.athlete_number.strip(),
        notes=athlete.notes.strip(), status=athlete.status.strip().lower(),
    )
    if not normalized.first_name or not normalized.last_name:
        raise ValueError("First name and last name are required.")
    if normalized.status not in ATHLETE_STATUSES:
        raise ValueError("Athlete status is invalid.")
    if normalized.graduation_year is not None and not 2000 <= normalized.graduation_year <= 2100:
        raise ValueError("Graduation year must be between 2000 and 2100.")
    return normalized
