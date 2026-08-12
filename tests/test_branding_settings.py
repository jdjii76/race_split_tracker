"""Persistence, caching, authorization, and upload validation tests."""
from types import SimpleNamespace
from split_tracker.branding import DEFAULT_SCHOOL_PROFILE, MAX_LOGO_BYTES, SchoolProfile, validate_logo_upload
from split_tracker.branding_service import authorize_settings, load_cached_profile, restore_defaults, save_profile, settings_editing_enabled
from split_tracker.repository import InMemoryRaceRepository


class Session(dict):
    pass


def test_missing_row_and_database_failure_use_fallback():
    session = Session()
    repo = InMemoryRaceRepository()
    profile, warning = load_cached_profile(session, repo, DEFAULT_SCHOOL_PROFILE)
    assert profile == DEFAULT_SCHOOL_PROFILE and warning is None

    class BrokenRepository:
        def get_school_profile(self):
            raise RuntimeError("database unavailable")

    profile, warning = load_cached_profile(Session(), BrokenRepository(), DEFAULT_SCHOOL_PROFILE)
    assert profile == DEFAULT_SCHOOL_PROFILE
    assert warning


def test_stored_profile_overrides_default_and_is_cached():
    class CountingRepository(InMemoryRaceRepository):
        reads = 0
        def get_school_profile(self):
            self.reads += 1
            return super().get_school_profile()

    repo = CountingRepository()
    repo.save_school_profile(SchoolProfile(short_name="CHS"))
    session = Session()
    assert load_cached_profile(session, repo, DEFAULT_SCHOOL_PROFILE)[0].short_name == "CHS"
    assert load_cached_profile(session, repo, DEFAULT_SCHOOL_PROFILE)[0].short_name == "CHS"
    assert repo.reads == 1


def test_authorization_requires_configured_matching_passcode():
    session = Session()
    assert not settings_editing_enabled(None)
    assert not authorize_settings(session, "anything", None)
    assert not authorize_settings(session, "wrong", "configured")
    assert authorize_settings(session, "configured", "configured")
    assert "configured" not in session.values()


def test_save_and_confirmed_restore_clear_cache():
    repo = InMemoryRaceRepository()
    session = Session(school_profile_cache=DEFAULT_SCHOOL_PROFILE)
    custom = SchoolProfile(short_name="CHS")
    save_profile(session, repo, custom)
    assert "school_profile_cache" not in session
    session["school_profile_cache"] = custom
    assert restore_defaults(session, repo, confirmed=False) is None
    assert repo.get_school_profile() == custom
    restore_defaults(session, repo, confirmed=True)
    assert "school_profile_cache" not in session
    assert repo.get_school_profile() == DEFAULT_SCHOOL_PROFILE


def test_logo_upload_rejects_invalid_type_and_oversize():
    assert validate_logo_upload("logo.svg", "image/svg+xml", 100)[1]
    assert validate_logo_upload("logo.png", "image/jpeg", 100)[1]
    assert validate_logo_upload("logo.png", "image/png", MAX_LOGO_BYTES + 1)[1]
    assert validate_logo_upload("logo.jpeg", "image/jpeg", 100) == (".jpeg", None)


def test_profile_repository_stores_paths_not_image_bytes():
    repo = InMemoryRaceRepository()
    saved = repo.save_school_profile(SchoolProfile(logo_path="schools/default/logo.png"))
    assert saved.logo_path == "schools/default/logo.png"
    assert isinstance(saved.logo_path, str)


def test_admin_branding_page_contains_sponsor_crud_and_supported_upload_types():
    source = open("pages/school_branding.py", encoding="utf-8").read()
    assert 'st.header("Sponsor Management")' in source
    assert 'type=["png", "jpg", "jpeg", "webp"]' in source
    for operation in ("create_sponsor", "update_sponsor", "delete_sponsor", "list_sponsors"):
        assert f"repository.{operation}" in source
