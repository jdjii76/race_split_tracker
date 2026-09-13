"""School profile, asset fallback, and export naming tests."""
from pathlib import Path
from split_tracker.branding import (
    DEFAULT_SCHOOL_PROFILE,
    FALLBACK_ACCENT,
    SchoolProfile,
    branded_export_filename,
    get_school_profile,
    load_school_profile,
    resolve_logo_path,
)


def test_kmhs_defaults_require_no_configuration():
    profile = get_school_profile(secrets={}, environ={})
    assert profile == DEFAULT_SCHOOL_PROFILE
    assert profile.school_name == "Kennesaw Mountain High School"
    assert profile.short_name == "KMHS"
    assert profile.program_name == "KMHS Cross Country"
    assert profile.mascot == "Mustangs"
    assert profile.app_title == "KMHS Running Splits"


def test_partial_secrets_override_defaults_and_environment():
    profile, warnings = load_school_profile(
        secrets={"school": {"short_name": "NHS", "program_name": ""}},
        environ={"SCHOOL_SHORT_NAME": "ENV"},
    )
    assert profile.short_name == "NHS"
    assert profile.program_name == "NHS Cross Country"
    assert profile.school_name == DEFAULT_SCHOOL_PROFILE.school_name
    assert not warnings


def test_invalid_colors_use_documented_fallback():
    profile, warnings = load_school_profile(secrets={"school": {"accent_color": "orange"}}, environ={})
    assert profile.accent_color == FALLBACK_ACCENT
    assert warnings


def test_missing_or_unsupported_logo_uses_text_fallback(tmp_path):
    unsupported = tmp_path / "logo.txt"
    unsupported.write_text("not an image")
    assert resolve_logo_path(None) is None
    assert resolve_logo_path(str(tmp_path / "missing.png")) is None
    assert resolve_logo_path(str(unsupported)) is None


def test_branded_filename_is_prefixed_and_portable():
    profile = SchoolProfile(short_name="KMHS")
    filename = branded_export_filename(profile, ["2026", "Cobb: County / Championship", "Boys  Varsity", "Results"], ".csv")
    assert filename == "KMHS_2026_Cobb_County_Championship_Boys_Varsity_Results.csv"


def test_app_uses_profile_title_and_timing_branding_has_no_repository_reads():
    root = Path(__file__).resolve().parents[1]
    app_source = (root / "app.py").read_text(encoding="utf-8")
    timing_source = (root / "pages/live_timing.py").read_text(encoding="utf-8")
    assert "page_title=school_profile.app_title" in app_source
    assert "render_school_header(" in timing_source
    assert "get_school_profile" not in timing_source
