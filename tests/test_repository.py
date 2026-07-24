"""Tests for Phase 1 meet/race/template repositories."""

from __future__ import annotations

from dataclasses import replace

from split_tracker.config import SupabaseConfig
from split_tracker.repository import (
    DEFAULT_XC_TEMPLATE_NAME,
    InMemoryRaceRepository,
    Meet,
    Race,
    RepositoryFactoryResult,
    SupabaseRaceRepository,
    TemplateRace,
    create_repository,
)
from split_tracker.state import load_race_into_setup


def test_create_update_archive_and_delete_draft_meet():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Creekside Invitational", season="2026 XC"))
    loaded = repo.get_meet(meet.id)
    updated = repo.update_meet(replace(meet, location="Creekside Park"))
    archived = repo.archive_meet(meet.id)
    draft = repo.create_meet(Meet(name="Draft Meet"))

    assert loaded == meet
    assert updated.location == "Creekside Park"
    assert archived.status == "archived"
    assert repo.delete_draft_meet(meet.id) is False
    assert repo.delete_draft_meet(draft.id) is True
    assert repo.get_meet(draft.id) is None


def test_create_four_races_and_load_in_display_order():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Creekside Invitational"))
    names = ["Boys JV", "Girls JV", "Boys Varsity", "Girls Varsity"]
    for index, name in enumerate(reversed(names)):
        repo.create_race(Race(meet_id=meet.id, name=name, distance_meters=5000.0, display_order=3 - index))

    races = repo.list_races_for_meet(meet.id)

    assert [race.name for race in races] == names


def test_update_archive_and_prevent_non_draft_race_delete():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Creekside Invitational"))
    race = repo.create_race(Race(meet_id=meet.id, name="Boys JV", distance_meters=5000.0))
    ready = repo.update_race(replace(race, status="ready"))
    archived = repo.archive_race(race.id)

    assert ready.status == "ready"
    assert archived.status == "archived"
    assert repo.delete_draft_race(race.id) is False


def test_duplicate_race_creates_new_draft_without_timing_data():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Creekside Invitational"))
    race = repo.create_race(Race(meet_id=meet.id, name="Boys Varsity", distance_meters=5000.0, status="completed", display_order=1))

    duplicate = repo.duplicate_race(race.id)

    assert duplicate.id != race.id
    assert duplicate.name == "Boys Varsity Copy"
    assert duplicate.status == "draft"
    assert duplicate.display_order == 2


def test_create_load_and_apply_default_xc_template_idempotently():
    repo = InMemoryRaceRepository()
    first = repo.seed_default_xc_template()
    second = repo.seed_default_xc_template()
    meet, races = repo.apply_template_to_meet(first.id, Meet(name="Creekside Invitational"))

    assert first.id == second.id
    assert len(repo.list_templates(include_archived=True)) == 1
    assert first.name == DEFAULT_XC_TEMPLATE_NAME
    assert repo.get_template(first.id) == first
    assert meet.name == "Creekside Invitational"
    assert [race.name for race in races] == ["Boys JV", "Girls JV", "Boys Varsity", "Girls Varsity"]
    assert len(races) == 4
    assert all(race.distance_meters == 5000.0 for race in races)


def test_create_custom_template_and_archive():
    repo = InMemoryRaceRepository()
    template = repo.create_template(
        template=repo.seed_default_xc_template().__class__(name="Track Quad"),
        races=[TemplateRace(template_id="ignored", name="1600 m", distance_meters=1600.0)],
    )
    archived = repo.archive_template(template.id)

    assert repo.get_template(template.id).name == "Track Quad"
    assert len(repo.list_template_races(template.id)) == 1
    assert archived.status == "archived"


def test_repository_factory_missing_configuration_falls_back_to_in_memory(monkeypatch):
    import split_tracker.repository as repository_module

    monkeypatch.setattr(repository_module, "load_supabase_config", lambda: SupabaseConfig())
    result = create_repository()

    assert isinstance(result.repository, InMemoryRaceRepository)
    assert result.is_temporary
    assert "temporary" in result.storage_label.lower()
    assert len(result.repository.list_template_races(result.repository.seed_default_xc_template().id)) == 4


def test_repository_factory_does_not_fallback_when_configured_supabase_fails(monkeypatch):
    import split_tracker.repository as repository_module

    monkeypatch.setattr(repository_module, "load_supabase_config", lambda: SupabaseConfig(url="https://configured.supabase.com", key="key", source="environment"))
    monkeypatch.setattr(repository_module, "create_supabase_connection", lambda config: (_ for _ in ()).throw(RuntimeError("network down")))

    result = create_repository()

    assert result.repository is None
    assert not result.is_temporary
    assert result.error is not None


def test_navigation_to_saved_race_loads_existing_setup():
    class Session(dict):
        def __getattr__(self, key):
            return self[key]
        def __setattr__(self, key, value):
            self[key] = value

    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Creekside Invitational"))
    race = repo.create_race(Race(meet_id=meet.id, name="Boys JV", distance_meters=5000.0, course_type="Cross Country"))
    session = Session(athletes=[], splits=[])

    load_race_into_setup(session, meet, race)

    assert session.selected_meet_id == meet.id
    assert session.selected_race_id == race.id
    assert session.meet_config.meet_name == meet.name
    assert session.meet_config.race_name == race.name
    assert session.meet_config.race_distance_meters == 5000.0


def test_repository_factory_uses_supabase_when_configuration_and_client_are_available(monkeypatch):
    import split_tracker.repository as repository_module
    from split_tracker.supabase_client import SupabaseConnectionResult

    monkeypatch.setattr(repository_module, "load_supabase_config", lambda: SupabaseConfig(url="https://configured.supabase.com", key="key", source="environment"))
    monkeypatch.setattr(repository_module.SupabaseRaceRepository, "seed_default_xc_template", lambda self: None)
    result = create_repository(connection_result=SupabaseConnectionResult(configured=True, message="ok", client=object()))

    assert isinstance(result.repository, SupabaseRaceRepository)
    assert not result.is_temporary
    assert result.storage_label == "Supabase"
