"""Formatting helpers for race timing values."""

from __future__ import annotations


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


def parse_pace_to_seconds(value: str | float | int | None) -> float | None:
    """Parse a pace value into seconds.

    Accepts blank values, numeric seconds, `M:SS`, `M:SS.hh`, or `H:MM:SS`.
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
