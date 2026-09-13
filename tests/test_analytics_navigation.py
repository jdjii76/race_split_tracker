"""Coach Analytics catalog, defaults, isolation, and contextual routing tests."""
from datetime import date, datetime, timezone
from pathlib import Path

from split_tracker.analytics_navigation import load_analytics_catalog, meet_label, resolve_analytics_option
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession


def catalog_fixture():
    repo = InMemoryRaceRepository()
    old = repo.create_meet(Meet("Old Invite", meet_date=date(2026, 8, 20), status="completed"))
    recent = repo.create_meet(Meet("Mustang Stampede", meet_date=date(2026, 9, 12), status="active"))
    archived = repo.create_meet(Meet("Archived", meet_date=date(2025, 9, 1), status="archived"))
    completed = repo.create_race(Race(recent.id, "Varsity Boys", 5000, status="completed"))
    review = repo.create_race(Race(recent.id, "JV Girls", 5000, status="ready"))
    cancelled = repo.create_race(Race(recent.id, "Cancelled", 3200, status="ready"))
    old_race = repo.create_race(Race(old.id, "Old Varsity", 5000, status="completed"))
    archived_race = repo.create_race(Race(archived.id, "Hidden", 5000, status="completed"))
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    sessions = [
        repo.create_race_session(RaceSession(completed.id, status="completed", created_at=now)),
        repo.create_race_session(RaceSession(review.id, status="awaiting_review", created_at=now)),
        repo.create_race_session(RaceSession(cancelled.id, status="cancelled", created_at=now)),
        repo.create_race_session(RaceSession(
            old_race.id, status="completed",
            created_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )),
        repo.create_race_session(RaceSession(archived_race.id, status="completed")),
    ]
    return repo, old, recent, completed, review, sessions


def test_catalog_contains_completed_and_review_ready_but_excludes_archived_cancelled():
    repo, old, recent, completed, review, _ = catalog_fixture()
    options = load_analytics_catalog(repo)
    assert {(item.meet.id, item.race.id, item.session.status) for item in options} == {
        (recent.id, completed.id, "completed"),
        (recent.id, review.id, "awaiting_review"),
        (old.id, next(r.id for r in repo.list_races_for_meet(old.id)), "completed"),
    }
    assert meet_label(recent) == "Mustang Stampede — Sep 12, 2026"


def test_races_are_scoped_to_meet_and_selection_persists_by_stable_id():
    repo, old, recent, completed, review, sessions = catalog_fixture()
    options = load_analytics_catalog(repo)
    recent_options = [item for item in options if item.meet.id == recent.id]
    assert {item.race.id for item in recent_options} == {completed.id, review.id}
    saved = resolve_analytics_option(
        options, saved_meet_id=recent.id, saved_race_id=review.id,
        saved_session_id=sessions[1].id, contextual_race_id=completed.id,
    )
    assert saved.race.id == review.id
    stale = resolve_analytics_option(options, saved_meet_id=old.id, saved_race_id="missing")
    assert stale.session.status == "completed" and stale.meet.id == recent.id


def test_contextual_then_active_then_recent_defaults_are_deterministic():
    repo, _, recent, completed, review, sessions = catalog_fixture()
    options = load_analytics_catalog(repo)
    contextual = resolve_analytics_option(
        options, contextual_race_id=review.id, contextual_session_id=sessions[1].id,
        active_race_id=completed.id,
    )
    assert contextual.race.id == review.id
    assert resolve_analytics_option(options, active_race_id=completed.id).race.id == completed.id
    assert resolve_analytics_option(options).race.id == completed.id
    assert contextual.meet.id == recent.id


def test_catalog_loads_metadata_only_and_empty_state_is_representable():
    class CountingRepository(InMemoryRaceRepository):
        active_event_queries = 0

        def list_active_split_events(self, race_session_id):
            self.active_event_queries += 1
            return super().list_active_split_events(race_session_id)

    repo = CountingRepository()
    repo.create_meet(Meet("No Results", status="active"))
    assert load_analytics_catalog(repo) == []
    assert repo.active_event_queries == 0
    assert resolve_analytics_option([], saved_race_id="stale") is None


def test_page_uses_dedicated_state_without_mutating_live_timing_context():
    source = Path("pages/coach_analytics.py").read_text()
    for key in ("coach_analytics_meet_id", "coach_analytics_race_id", "coach_analytics_session_id"):
        assert key in source
    for protected_key in ("active_race_session_id", "timer_station", "pack_device_id", "timing_mode"):
        assert f"{protected_key} =" not in source and f'["{protected_key}"] =' not in source
    assert "No completed or review-ready races are available for Coach Analytics." in source
    assert 'st.session_state.pop("team_position_filter"' in source
    assert 'st.session_state.pop("coach_analytics_athlete_id"' in source
    assert 'st.header("Coach Analytics")' in source
    assert 'st.selectbox("Meet"' in source and 'st.selectbox(\n        "Race"' in source
    assert "with st.sidebar" not in source
    assert "No races in this meet are currently available for Coach Analytics." in source


def test_coach_analytics_remains_one_normal_sidebar_navigation_page():
    source = Path("app.py").read_text()
    assert source.count("COACH_ANALYTICS_PAGE = st.Page(") == 1
    assert 'title="Coach Analytics"' in source
    assert source.count("race_day_pages.insert(4, COACH_ANALYTICS_PAGE)") == 1


def test_race_day_and_results_context_links_preselect_dedicated_analytics_ids():
    dashboard = Path("pages/meet_dashboard.py").read_text()
    results = Path("pages/results.py").read_text()
    for source in (dashboard, results):
        assert "coach_analytics_meet_id" in source
        assert "coach_analytics_race_id" in source
        assert "coach_analytics_session_id" in source
