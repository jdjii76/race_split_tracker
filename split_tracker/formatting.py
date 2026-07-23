"""Formatting helpers for race timing and distance values."""

from __future__ import annotations

METERS_PER_MILE = 1609.344


def format_duration(seconds: float | None) -> str:
    """Format seconds as M:SS.hh or H:MM:SS.hh."""
    if seconds is None:
        return "—"
    sign = "-" if seconds < 0 else ""
    total_hundredths = round(abs(seconds) * 100)
    whole_seconds, hundredths = divmod(total_hundredths, 100)
    minutes_total, secs = divmod(whole_seconds, 60)
    hours, minutes = divmod(minutes_total, 60)
    if hours:
        return f"{sign}{hours}:{minutes:02d}:{secs:02d}.{hundredths:02d}"
    return f"{sign}{minutes}:{secs:02d}.{hundredths:02d}"


def format_pace(seconds_per_mile: float | None) -> str:
    """Format a per-mile pace value."""
    if seconds_per_mile is None:
        return "—"
    return f"{format_duration(seconds_per_mile)}/mi"


def parse_time_to_seconds(value: str | float | int | None) -> float | None:
    """Parse a duration into seconds.

    Accepts blank values, numeric seconds, `MM:SS`, `MM:SS.hh`, or `HH:MM:SS`.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value) if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        if ":" not in text:
            numeric = float(text)
            return numeric if numeric > 0 else None
        parts = [float(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        minutes, seconds = parts
        total = minutes * 60 + seconds
    elif len(parts) == 3:
        hours, minutes, seconds = parts
        total = hours * 3600 + minutes * 60 + seconds
    else:
        return None
    return total if total > 0 else None


def parse_pace_to_seconds(value: str | float | int | None) -> float | None:
    """Parse a per-mile pace value into seconds."""
    return parse_time_to_seconds(value)


def format_distance(meters: float) -> str:
    """Format a distance using familiar coaching units."""
    if abs(meters - METERS_PER_MILE) < 0.5:
        return "1 mile"
    if meters >= 1609.344 and abs(meters / METERS_PER_MILE - round(meters / METERS_PER_MILE)) < 0.01:
        miles = round(meters / METERS_PER_MILE)
        return f"{miles} miles"
    if meters >= 1000 and abs(meters % 1000) < 0.01:
        return f"{meters / 1000:g}K"
    return f"{meters:g} m"


def parse_distance_to_meters(value: str | float | int | None) -> float | None:
    """Parse a distance into meters from m, km/K, mile/mi, or raw meter values."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value) if value > 0 else None
    text = str(value).strip().lower()
    if not text:
        return None
    if text == "finish":
        return None
    multiplier = 1.0
    for suffix, factor in (("miles", METERS_PER_MILE), ("mile", METERS_PER_MILE), ("mi", METERS_PER_MILE), ("km", 1000.0), ("k", 1000.0), ("m", 1.0)):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier = factor
            break
    try:
        distance = float(text) * multiplier
    except ValueError:
        return None
    return distance if distance > 0 else None
