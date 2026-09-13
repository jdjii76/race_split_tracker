"""Application-level school identity, validation, rendering, and exports."""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping

# Temporary, non-authoritative fallback colors chosen for accessible UI contrast.
# Replace through configuration when approved school colors are supplied.
FALLBACK_PRIMARY = "#243447"
FALLBACK_SECONDARY = "#F5F7FA"
FALLBACK_ACCENT = "#B7791F"
FALLBACK_TEXT_ON_PRIMARY = "#FFFFFF"
SUPPORTED_LOGO_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg"}
UPLOAD_LOGO_SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_LOGO_BYTES = 5 * 1024 * 1024
HEADER_STYLES = {"standard", "logo_left", "compact", "text_only"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SchoolProfile:
    school_name: str = "Kennesaw Mountain High School"
    short_name: str = "KMHS"
    program_name: str = "KMHS Cross Country"
    mascot: str = "Mustangs"
    city: str = "Kennesaw"
    state: str = "Georgia"
    primary_color: str = FALLBACK_PRIMARY
    secondary_color: str = FALLBACK_SECONDARY
    accent_color: str = FALLBACK_ACCENT
    text_on_primary: str = FALLBACK_TEXT_ON_PRIMARY
    logo_path: str | None = None
    compact_logo_path: str | None = None
    app_title: str = "KMHS Running Splits"
    header_style: str = "standard"
    show_logo_on_dashboard: bool = True
    show_logo_on_timing: bool = True
    include_branding_on_exports: bool = True


DEFAULT_SCHOOL_PROFILE = SchoolProfile()
_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _value(mapping: object | None, key: str) -> object | None:
    if mapping is None:
        return None
    try:
        return mapping.get(key) if isinstance(mapping, Mapping) else mapping[key]  # type: ignore[index]
    except Exception:
        return None


def load_school_profile(*, secrets: object | None = None, environ: Mapping[str, str] | None = None, application_config: Mapping[str, object] | None = None) -> tuple[SchoolProfile, tuple[str, ...]]:
    """Load validated defaults <- app config <- environment <- secrets overrides."""
    env = os.environ if environ is None else environ
    school_secrets = _value(secrets, "school")
    values = {field.name: getattr(DEFAULT_SCHOOL_PROFILE, field.name) for field in fields(SchoolProfile)}
    warnings: list[str] = []
    for name in values:
        configured = _value(application_config, name)
        env_value = env.get(f"SCHOOL_{name.upper()}")
        secret_value = _value(school_secrets, name)
        selected = secret_value if secret_value is not None else env_value if env_value is not None else configured
        if selected is not None:
            if isinstance(getattr(DEFAULT_SCHOOL_PROFILE, name), bool):
                values[name] = selected if isinstance(selected, bool) else str(selected).strip().lower() in {"1", "true", "yes", "on"}
            else:
                values[name] = str(selected).strip() or None
    for required in ("school_name", "short_name"):
        if not values[required]:
            values[required] = getattr(DEFAULT_SCHOOL_PROFILE, required)
            warnings.append(f"Blank {required} used the safe default.")
    if not values["program_name"]:
        values["program_name"] = f"{values['short_name']} Cross Country"
    for color_name in ("primary_color", "secondary_color", "accent_color", "text_on_primary"):
        if not isinstance(values[color_name], str) or not _COLOR_PATTERN.fullmatch(values[color_name]):
            values[color_name] = getattr(DEFAULT_SCHOOL_PROFILE, color_name)
            warnings.append(f"Invalid {color_name} used the temporary fallback.")
    if values["header_style"] not in HEADER_STYLES:
        values["header_style"] = DEFAULT_SCHOOL_PROFILE.header_style
        warnings.append("Invalid header_style used the standard layout.")
    return SchoolProfile(**values), tuple(warnings)


def get_school_profile(*, secrets: object | None = None, environ: Mapping[str, str] | None = None) -> SchoolProfile:
    return load_school_profile(secrets=secrets, environ=environ)[0]


def resolve_logo_path(path: str | None) -> Path | None:
    """Resolve a supported local logo, returning None for every invalid input."""
    if not path:
        return None
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    try:
        return candidate if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_LOGO_SUFFIXES else None
    except OSError:
        return None


def branded_export_filename(profile: SchoolProfile, parts: list[object], extension: str) -> str:
    """Create a portable school-prefixed filename without changing export data."""
    tokens = ([profile.short_name] if profile.include_branding_on_exports else []) + [str(part) for part in parts if str(part).strip()]
    stem = "_".join(tokens)
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem)
    stem = re.sub(r"[\s_-]+", "_", stem).strip("._")
    suffix = re.sub(r"[^A-Za-z0-9]", "", extension.lstrip(".")) or "csv"
    return f"{stem}.{suffix.lower()}"


def apply_school_theme(profile: SchoolProfile) -> None:
    import streamlit as st
    st.markdown(f"""<style>
:root {{--school-primary:{profile.primary_color};--school-accent:{profile.accent_color};}}
[data-testid="stSidebar"] {{border-right: 3px solid {profile.accent_color};}}
.kmhs-header {{background:{profile.primary_color};color:{profile.text_on_primary};border-left:.45rem solid {profile.accent_color};padding:.65rem 1rem;border-radius:.45rem;margin:0 0 .8rem;}}
.kmhs-header.compact {{padding:.38rem .75rem;margin-bottom:.45rem;}}
.kmhs-eyebrow {{font-size:.76rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;}}
.kmhs-title {{font-size:clamp(1.25rem,3vw,2rem);font-weight:750;line-height:1.15;overflow-wrap:anywhere;}}
.kmhs-meta {{font-size:.88rem;opacity:.9;overflow-wrap:anywhere;}}
.kmhs-sidebar {{line-height:1.05;margin-bottom:.4rem;}}
.kmhs-sidebar strong {{font-size:1.3rem;color:{profile.primary_color};}}
@media(max-width:640px){{.kmhs-header{{padding:.45rem .65rem}}.kmhs-meta{{font-size:.78rem}}}}
</style>""", unsafe_allow_html=True)


def render_school_header(profile: SchoolProfile, title: str, *, subtitle: str | None = None, compact: bool = False) -> None:
    """Render one responsive branded header; logo lookup never blocks rendering."""
    import streamlit as st
    configured_logo = profile.compact_logo_path if compact else profile.logo_path
    show_logo = profile.show_logo_on_timing if compact else profile.show_logo_on_dashboard
    logo = resolve_logo_path(configured_logo) if show_logo and profile.header_style != "text_only" else None
    remote_logo = configured_logo if show_logo and configured_logo and str(configured_logo).startswith(("https://", "http://")) else None
    if logo or remote_logo:
        logo_col, text_col = st.columns([1, 6], vertical_alignment="center")
        logo_col.image(str(logo or remote_logo), width=72 if compact else 110)
        target = text_col
    else:
        target = st
    location = " • ".join(item for item in (profile.school_name, profile.mascot, subtitle) if item)
    use_compact = compact or profile.header_style == "compact"
    target.markdown(
        f'<div class="kmhs-header{" compact" if use_compact else ""}"><div class="kmhs-eyebrow">{html.escape(profile.program_name)}</div>'
        f'<div class="kmhs-title">{html.escape(title)}</div><div class="kmhs-meta">{html.escape(location)}</div></div>',
        unsafe_allow_html=True,
    )


def render_school_sidebar_brand(profile: SchoolProfile) -> None:
    import streamlit as st
    logo = resolve_logo_path(profile.compact_logo_path)
    if logo:
        st.image(str(logo), width=72)
    else:
        st.markdown(f'<div class="kmhs-sidebar"><strong>{html.escape(profile.short_name)}</strong><br>Cross Country</div>', unsafe_allow_html=True)


def validate_profile(profile: SchoolProfile) -> tuple[list[str], list[str]]:
    """Return blocking errors and non-blocking accessibility warnings."""
    errors: list[str] = []
    warnings: list[str] = []
    for label, value in (("School name", profile.school_name), ("Short name", profile.short_name), ("App title", profile.app_title)):
        if not value.strip():
            errors.append(f"{label} is required.")
    for name in ("primary_color", "secondary_color", "accent_color", "text_on_primary"):
        if not _COLOR_PATTERN.fullmatch(getattr(profile, name)):
            errors.append(f"{name.replace('_', ' ').title()} must be a six-digit hexadecimal color.")
    if profile.header_style not in HEADER_STYLES:
        errors.append("Select a supported header style.")
    if not errors and contrast_ratio(profile.primary_color, profile.text_on_primary) < 4.5:
        warnings.append("Primary background and header text have low contrast (below 4.5:1).")
    if not errors and contrast_ratio(profile.secondary_color, profile.primary_color) < 3:
        warnings.append("Secondary and primary colors may be difficult to distinguish.")
    return errors, warnings


def contrast_ratio(first: str, second: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        channels = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in channels]
        return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2]
    bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (bright + .05) / (dark + .05)


def validate_logo_upload(name: str, mime_type: str, size: int, *, max_bytes: int = MAX_LOGO_BYTES) -> tuple[str | None, str | None]:
    """Validate a logo without reading or persisting its bytes."""
    suffix = Path(name).suffix.lower()
    expected_mime = UPLOAD_LOGO_SUFFIXES.get(suffix)
    if expected_mime is None or mime_type != expected_mime:
        return None, "Upload a PNG, JPG, or JPEG image with a matching file type."
    if size > max_bytes:
        return None, f"Logo must be {max_bytes // (1024 * 1024)} MB or smaller."
    return suffix, None
