"""Read-only spectator resolution, projection, isolation, and security tests."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from split_tracker.models import Athlete, Checkpoint
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, SplitEvent
from split_tracker.spectator import (
    ReadOnlySpectatorRepository,
    SpectatorAthleteRow,
    _public_session,
    load_spectator_race,
    spectator_status,
    spectator_elapsed_seconds,
    spectator_url,
)
from pages.spectator import _athlete_card_html, _race_clock_html


def _fixture():
    repo = InMemoryRaceRepository()
    meet = repo.create_meet(Meet(name="Invite"))
    race_a = repo.create_race(Race(meet_id=meet.id, name="Varsity", distance_meters=3200))
    race_b = repo.create_race(Race(meet_id=meet.id, name="Varsity", distance_meters=3200))
    repo.replace_race_athletes(race_a.id, [Athlete("Jordan Lee", athlete_id="a")])
    repo.replace_race_athletes(race_b.id, [Athlete("Jordan Lee", athlete_id="b")])
    session_a = repo.create_race_session(RaceSession(race_id=race_a.id, status="running"))
    session_b = repo.create_race_session(RaceSession(race_id=race_b.id, status="running"))
    checkpoints = [Checkpoint(1, "Mile 1", 1609.344), Checkpoint(2, "Finish", 3200, True)]
    repo.create_race_session_checkpoints(session_a.id, checkpoints)
    repo.create_race_session_checkpoints(session_b.id, checkpoints)
    return repo, race_a, race_b, session_a, session_b


def _event(repo, session_id, athlete_id, checkpoint, elapsed, order, **kwargs):
    return repo.create_split_event(SplitEvent(
        race_session_id=session_id, athlete_id=athlete_id, athlete_name="Jordan Lee",
        checkpoint_number=checkpoint, checkpoint_label="Finish" if checkpoint == 2 else "Mile 1",
        elapsed_seconds=elapsed, event_order=order, **kwargs,
    ))


def test_public_ids_resolve_exact_race_and_session_without_browser_state():
    repo, race_a, race_b, session_a, session_b = _fixture()
    view = load_spectator_race(ReadOnlySpectatorRepository(repo), race_id=race_a.id, session_id=session_a.id)

    assert view.race.id == race_a.id and view.session.id == session_a.id
    assert load_spectator_race(repo, race_id=race_a.id, session_id=session_b.id) is None
    assert load_spectator_race(repo, race_id="invalid") is None
    assert spectator_url(race_b.id, session_b.id).endswith(
        f"spectator_race={race_b.id}&spectator_session={session_b.id}"
    )


def test_absolute_spectator_urls_normalize_and_encode_all_variants():
    race_id = "race id/with symbols"
    assert spectator_url(race_id, base_url="https://kmhs-race-timer.streamlit.app") == (
        "https://kmhs-race-timer.streamlit.app/live-race?spectator_race=race+id%2Fwith+symbols"
    )
    exact = spectator_url(
        "race-uuid", "session-uuid", base_url="https://kmhs-race-timer.streamlit.app/"
    )
    assert exact == (
        "https://kmhs-race-timer.streamlit.app/live-race?"
        "spectator_race=race-uuid&spectator_session=session-uuid"
    )
    assert "//live-race" not in exact and exact.count("?") == 1
    assert spectator_url("race-uuid").startswith("http://localhost:8501/live-race?")


def test_mobile_card_groups_name_authoritative_time_and_progress():
    row = SpectatorAthleteRow(
        name="Alex Smith", team="KMHS", latest_checkpoint="Mile 2",
        cumulative_time="10:42.00", next_checkpoint="Finish", status="In Progress",
    )
    html = _athlete_card_html(1, row)
    assert "Alex Smith" in html and "10:42.00" in html
    assert "Mile 2 · Next: Finish · In Progress" in html
    assert html.index("Alex Smith") < html.index("10:42.00") < html.index("Mile 2")


def test_dnf_card_prioritizes_dnf_but_preserves_partial_time():
    row = SpectatorAthleteRow(
        name="David Green", team="", latest_checkpoint="Mile 2",
        cumulative_time="11:12.00", next_checkpoint="—", status="DNF",
    )
    html = _athlete_card_html(4, row)
    assert "DNF" in html and "Mile 2 · 11:12.00" in html


def test_spectator_adapter_exposes_reads_but_no_mutation_capabilities():
    adapter = ReadOnlySpectatorRepository(_fixture()[0])
    for mutation in ("record_shared_split", "invalidate_split_event", "set_race_athlete_dnf", "finalize_race_session"):
        assert not hasattr(adapter, mutation)


def test_projection_is_session_isolated_and_reflects_corrections_and_dnf():
    repo, race_a, race_b, session_a, session_b = _fixture()
    wrong = _event(repo, session_a.id, "a", 1, 400, 1)
    repo.invalidate_split_event(wrong.id, session_a.id, "a", 1, "Coach")
    _event(repo, session_a.id, "a", 1, 350, 2, correction_type="manual")
    repo.set_race_athlete_dnf(session_a.id, "a", "Coach")
    _event(repo, session_b.id, "b", 1, 999, 1)

    first = load_spectator_race(repo, race_id=race_a.id, session_id=session_a.id)
    second = load_spectator_race(repo, race_id=race_b.id, session_id=session_b.id)

    assert first.athlete_rows[0].cumulative_time == "5:50.00"
    assert first.athlete_rows[0].status == "DNF"
    assert second.athlete_rows[0].cumulative_time == "16:39.00"


def test_statuses_and_reopened_session_follow_authoritative_lifecycle():
    assert spectator_status(None) == "Not Started"
    for persisted, public in [("ready", "Not Started"), ("running", "Running"), ("paused", "Paused"), ("completed", "Finished")]:
        assert spectator_status(RaceSession(race_id="race", status=persisted)) == public
    assert spectator_status(replace(RaceSession(race_id="race", status="completed"), status="paused")) == "Paused"


def test_spectator_clock_uses_authoritative_running_and_frozen_elapsed_time():
    now = datetime(2026, 9, 4, 18, 22, tzinfo=timezone.utc)
    running = RaceSession(
        race_id="race", status="running", started_at=now - timedelta(seconds=42),
        elapsed_offset_seconds=1080,
    )
    assert spectator_elapsed_seconds(running, now=now) == 1122
    for status in ("paused", "awaiting_review", "completed"):
        frozen = replace(running, status=status, elapsed_offset_seconds=1122)
        assert spectator_elapsed_seconds(frozen, now=now + timedelta(hours=1)) == 1122


def test_public_session_retains_canonical_timing_timestamps_after_reopen():
    session = _public_session({
        "id": "session", "race_id": "race", "status": "running",
        "started_at": "2026-09-04T18:04:17Z", "paused_at": None,
        "ended_at": None, "elapsed_offset_seconds": 600,
    })
    now = datetime(2026, 9, 4, 18, 6, 19, tzinfo=timezone.utc)
    assert session.started_at == datetime(2026, 9, 4, 18, 4, 17, tzinfo=timezone.utc)
    assert spectator_elapsed_seconds(session, now=now) == 722


def test_spectator_clock_ticks_in_browser_without_polling_or_writes():
    start = datetime(2026, 9, 4, 18, 4, 17, tzinfo=timezone.utc)
    html = _race_clock_html(
        RaceSession(race_id="race", status="running", started_at=start),
        now=start + timedelta(minutes=18, seconds=42),
    )
    assert '"elapsed": 1122.0' in html
    assert "performance.now()" in html and "setInterval(renderClock, 250)" in html
    assert "Started ${started}" in html
    assert "fetch(" not in html and "supabase" not in html.lower()


def test_spectator_clock_labels_ready_and_paused_lifecycle_states():
    assert "Race has not started" in _race_clock_html(None)
    paused = RaceSession(race_id="race", status="paused", elapsed_offset_seconds=75)
    html = _race_clock_html(paused)
    assert '"status": "Paused"' in html and '"running": false' in html


def test_finished_view_reuses_results_ranking_and_places_dnf_last():
    repo, race_a, _, session_a, _ = _fixture()
    second = Athlete("Avery", athlete_id="c")
    repo.replace_race_athletes(race_a.id, [Athlete("Jordan Lee", athlete_id="a"), second])
    _event(repo, session_a.id, "a", 1, 300, 1)
    _event(repo, session_a.id, "a", 2, 620, 2)
    _event(repo, session_a.id, "c", 1, 330, 3)
    repo.set_race_athlete_dnf(session_a.id, "c", "Coach")
    repo.finalize_race_session(session_a.id)

    view = load_spectator_race(repo, race_id=race_a.id, session_id=session_a.id)
    assert [(row["Athlete"], row["Place"], row["Status"]) for row in view.final_rows] == [
        ("Jordan Lee", 1, "Finished"), ("Avery", "—", "DNF")
    ]


def test_spectator_page_is_display_only_and_polls_at_five_seconds():
    source = open("pages/spectator.py", encoding="utf-8").read()
    assert "st.button" not in source and "st.form" not in source
    assert "record_shared_split" not in source and "finalize_race_session" not in source
    assert "st.fragment(run_every=5)" in source
    assert "components.html(_race_clock_html(view.session)" in source


def test_spectator_uses_public_views_after_security_hardening():
    source = open("split_tracker/spectator.py", encoding="utf-8").read()
    for view in ("spectator_races", "spectator_sessions", "spectator_roster", "spectator_split_events"):
        assert view in source
