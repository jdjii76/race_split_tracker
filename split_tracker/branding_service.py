"""Cached branding persistence and administrative authorization helpers."""
from __future__ import annotations
import hmac
from split_tracker.branding import DEFAULT_SCHOOL_PROFILE, SchoolProfile

CACHE_KEY = "school_profile_cache"
AUTH_KEY = "school_settings_authorized"


def load_cached_profile(session_state, repository, fallback: SchoolProfile) -> tuple[SchoolProfile, str | None]:
    """Read branding at most once per browser session and always return a fallback."""
    cached = session_state.get(CACHE_KEY)
    if cached is not None:
        return cached, None
    try:
        stored = repository.get_school_profile() if repository is not None else None
        profile = stored or fallback
        session_state[CACHE_KEY] = profile
        return profile, None
    except Exception:
        session_state[CACHE_KEY] = fallback
        return fallback, "Saved branding is unavailable; built-in branding is active."


def clear_profile_cache(session_state) -> None:
    session_state.pop(CACHE_KEY, None)
    session_state.pop("school_branding_asset_urls", None)


def settings_editing_enabled(configured_passcode: str | None) -> bool:
    return bool(configured_passcode and configured_passcode.strip())


def authorize_settings(session_state, entered_passcode: str, configured_passcode: str | None) -> bool:
    """Authorize this browser session without retaining the entered passcode."""
    allowed = settings_editing_enabled(configured_passcode) and hmac.compare_digest(entered_passcode, configured_passcode or "")
    session_state[AUTH_KEY] = bool(allowed)
    return bool(allowed)


def save_profile(session_state, repository, profile: SchoolProfile) -> SchoolProfile:
    saved = repository.save_school_profile(profile)
    clear_profile_cache(session_state)
    return saved


def restore_defaults(session_state, repository, *, confirmed: bool) -> SchoolProfile | None:
    if not confirmed:
        return None
    saved = repository.restore_default_school_profile()
    clear_profile_cache(session_state)
    return saved
