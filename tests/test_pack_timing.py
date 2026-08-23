from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from split_tracker.models import Athlete, Checkpoint
from split_tracker.pack_timing import expected_arrival_metadata, normalize_pack_batch
from split_tracker.projection import project_race_state
from split_tracker.repository import InMemoryRaceRepository, Meet, Race, RaceSession, RepositoryError


def test_browser_component_uses_durable_queue_and_no_streamlit_button_cycle():
    source = open("split_tracker/pack_component/frontend/index.html", encoding="utf-8").read()
    assert "localStorage.setItem" in source and "localStorage.getItem" in source
    assert "performance.now()" in source and "Date.now()" in source
    assert "setTimeout(()=>emit(),500)" in source


def test_browser_component_confirms_taps_before_sync_and_keeps_recent_undo_visible():
    source = open("split_tracker/pack_component/frontend/index.html", encoding="utf-8").read()

    capture = source[source.index("function capture"):source.index("function undo")]
    assert capture.index("persist()") < capture.index("emit()")
    assert "lastCapturedId" in capture and "render()" in capture
    assert "Recent Captures · newest first" in source
    assert "UNDO LAST TAP" in source
    assert "undo_synced:" in source
    assert "Saved on device" in source and "Synchronized" in source


def test_pack_grid_keeps_captured_athletes_in_stable_all_athletes_view():
    source = open("split_tracker/pack_component/frontend/index.html", encoding="utf-8").read()
    render = source[source.index("function render"):source.index("addEventListener('message'")]

    assert "byAthlete=new Map" in render
    assert "All Athletes" in render
    assert "Remaining Only" in render
    assert "Captured Only" in render
    assert "Live order" not in render
    assert "!captured.has(a.id)" not in render
    assert "event=byAthlete.get(a.id)" in render
    assert "captured-at" in render
    assert "✓ " in render
    assert "${a.name}" in render
    assert "${a.last.toUpperCase()}" not in render
    assert "${a.bib? a.bib+'  ':''}" in render
    assert "Stable Roster" in render
    assert "Expected Arrival Order" in render
    assert "displayMode='stable'" in source


def test_expected_arrival_metadata_sorts_prior_times_and_marks_missing():
    checkpoints = [Checkpoint(1, "Mile 1", 1609), Checkpoint(2, "Mile 2", 3218)]
    states = [
        SimpleNamespace(athlete=SimpleNamespace(athlete_id="john"), splits=(SimpleNamespace(checkpoint_number=1, cumulative_time_seconds=362.0),)),
        SimpleNamespace(athlete=SimpleNamespace(athlete_id="alex"), splits=(SimpleNamespace(checkpoint_number=1, cumulative_time_seconds=375.0),)),
        SimpleNamespace(athlete=SimpleNamespace(athlete_id="sarah"), splits=(SimpleNamespace(checkpoint_number=1, cumulative_time_seconds=381.0),)),
        SimpleNamespace(athlete=SimpleNamespace(athlete_id="chris"), splits=()),
    ]

    metadata = expected_arrival_metadata(states, checkpoints, 2)
    ordered = sorted(
        metadata,
        key=lambda athlete_id: (
            metadata[athlete_id]["arrival_time"] is None,
            metadata[athlete_id]["arrival_time"] or 0,
        ),
    )

    assert ordered == ["john", "alex", "sarah", "chris"]
    assert metadata["chris"]["missing_previous"] is True
    assert metadata["chris"]["missing_label"] == "Mile 1"
    assert metadata["john"]["missing_previous"] is False


def test_expected_arrival_order_is_snapshotted_and_capture_does_not_resort():
    source = open("split_tracker/pack_component/frontend/index.html", encoding="utf-8").read()

    assert "expected-order" in source
    assert "expectedOrder.length" in source
    assert "expectedPosition=new Map" in source
    capture = source[source.index("function capture"):source.index("function undo")]
    assert "expectedOrder" not in capture


def test_pack_undo_void_ack_restores_uncaptured_card_without_deleting_history():
    source = open("split_tracker/pack_component/frontend/index.html", encoding="utf-8").read()

    assert "void_ids" in source
    assert "x.state='cancelled'" in source
    assert "undo_synced:" in source


def setup_repo():
    repo=InMemoryRaceRepository(); meet=repo.create_meet(Meet(name="Pack")); race=repo.create_race(Race(meet_id=meet.id,name="5K",distance_meters=5000,status="running"))
    athletes=[Athlete(name=n,bib_number=str(i+1)) for i,n in enumerate(["Emma Smith","Ava Jones","Mia Miller","Ivy Davis","Zoe Clark"])]
    repo.replace_race_athletes(race.id,athletes); start=datetime.now(timezone.utc)-timedelta(seconds=30)
    session=repo.create_race_session(RaceSession(race_id=race.id,status="running",started_at=start)); repo.create_race_session_checkpoints(session.id,[Checkpoint(1,"Mile 1",1609)])
    return repo,race,session,athletes,start


def batch(session,athletes,start):
    return [{"client_event_id":str(uuid4()),"athlete_id":a.athlete_id,"race_session_id":session.id,"checkpoint_number":1,"captured_at":(start+timedelta(seconds=10+i/10)).isoformat(),"capture_sequence":i+1,"device_id":"device-a","clock_offset_ms":12} for i,a in enumerate(athletes)]


def test_five_event_batch_order_idempotency_and_projection():
    repo,race,session,athletes,start=setup_repo(); payload=batch(session,athletes,start)
    saved=normalize_pack_batch(repo,race.id,session.id,1,list(reversed(payload)),"coach")
    assert len(saved)==5
    assert [e.capture_sequence for e in repo.list_all_split_events(session.id)]==[1,2,3,4,5]
    assert len(normalize_pack_batch(repo,race.id,session.id,1,payload,"coach"))==5
    assert len(repo.list_all_split_events(session.id))==5
    projection=project_race_state(session,athletes,[Checkpoint(1,"Mile 1",1609)],repo.list_all_split_events(session.id))
    assert len(projection.events)==5 and len(projection.results_rows)==5


def test_duplicate_logical_split_is_audited_not_projected():
    repo,race,session,athletes,start=setup_repo(); first=batch(session,athletes[:1],start); second=batch(session,athletes[:1],start); second[0]["device_id"]="device-b"
    normalize_pack_batch(repo,race.id,session.id,1,first,"a"); normalize_pack_batch(repo,race.id,session.id,1,second,"b")
    events=repo.list_all_split_events(session.id); assert len(events)==2 and events[1].event_type=="pack_conflict"
    assert len(project_race_state(session,athletes,[Checkpoint(1,"Mile 1",1609)],events).events)==1


def test_pack_rejects_wrong_or_completed_session():
    repo,race,session,athletes,start=setup_repo(); payload=batch(session,athletes[:1],start)
    with pytest.raises(RepositoryError): normalize_pack_batch(repo,"wrong",session.id,1,payload,"coach")
    repo.update_race_session(RaceSession(**{**session.__dict__,"status":"completed"}))
    with pytest.raises(RepositoryError): normalize_pack_batch(repo,race.id,session.id,1,payload,"coach")


def test_pack_event_uses_append_only_void():
    repo,race,session,athletes,start=setup_repo(); event=normalize_pack_batch(repo,race.id,session.id,1,batch(session,athletes[:1],start),"coach")[0]
    void=repo.invalidate_split_event(event.id,session.id,event.athlete_id,1,"coach")
    assert void.event_type=="split_voided" and len(repo.list_all_split_events(session.id))==2 and repo.list_active_split_events(session.id)==[]


def test_two_timer_stations_capture_independent_batches_in_one_session():
    repo, race, session, athletes, start = setup_repo()
    repo.race_session_checkpoints.clear()
    repo.create_race_session_checkpoints(
        session.id,
        [Checkpoint(1, "Mile 1", 1609), Checkpoint(2, "Mile 2", 3218)],
    )
    mile_one = batch(session, athletes[:2], start)
    mile_two = batch(session, athletes[2:4], start)
    for index, event in enumerate(mile_two, start=1):
        event["checkpoint_number"] = 2
        event["device_id"] = "device-b"
        event["capture_sequence"] = index

    first_saved = normalize_pack_batch(repo, race.id, session.id, 1, mile_one, "mile-one")
    second_saved = normalize_pack_batch(repo, race.id, session.id, 2, mile_two, "mile-two")

    assert {event.checkpoint_number for event in first_saved} == {1}
    assert {event.checkpoint_number for event in second_saved} == {2}
    assert {event.device_id for event in repo.list_all_split_events(session.id)} == {"device-a", "device-b"}
