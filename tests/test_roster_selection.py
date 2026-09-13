"""Race-scoped permanent-roster selection state behavior."""

from split_tracker.roster_selection import (
    athlete_checkbox_key,
    clear_race_checkbox_state,
    initialize_athlete_checkbox,
    persisted_selection_changed,
    selection_dirty_key,
    selection_key,
    set_race_selection,
    synchronize_race_selection,
    update_athlete_selection,
)


def test_initial_load_and_refresh_follow_persisted_selection():
    state = {}
    assert synchronize_race_selection(state, "race-a", ["a1", "a2"]) == ["a1", "a2"]
    checkbox = initialize_athlete_checkbox(state, "race-a", "a1", ["a1", "a2"])
    assert state[checkbox] is True

    assert synchronize_race_selection(state, "race-a", ["a2", "a3"]) == ["a2", "a3"]
    assert checkbox not in state
    assert (
        state[initialize_athlete_checkbox(state, "race-a", "a1", ["a2", "a3"])] is False
    )
    assert (
        state[initialize_athlete_checkbox(state, "race-a", "a3", ["a2", "a3"])] is True
    )


def test_unsaved_edits_are_preserved_and_external_change_is_visible():
    state = {}
    synchronize_race_selection(state, "race-a", ["a1"])
    update_athlete_selection(state, "race-a", "a2", True)

    assert synchronize_race_selection(state, "race-a", ["a3"]) == ["a1", "a2"]
    assert persisted_selection_changed(state, "race-a", ["a3"])
    assert state[selection_dirty_key("race-a")] is True

    set_race_selection(state, "race-a", ["a3"], saved=True)
    assert state[selection_key("race-a")] == ["a3"]
    assert not state[selection_dirty_key("race-a")]


def test_selection_updates_never_rewrite_existing_widget_keys():
    state = {}
    synchronize_race_selection(state, "race-a", ["a1"])
    checkbox = initialize_athlete_checkbox(state, "race-a", "a1", ["a1"])
    state[checkbox] = False  # Streamlit has supplied the new widget value.

    update_athlete_selection(state, "race-a", "a1", False)

    assert state[checkbox] is False
    assert state[selection_key("race-a")] == []


def test_checkbox_reset_is_race_scoped():
    state = {}
    first = initialize_athlete_checkbox(state, "race-a", "same-id", ["same-id"])
    second = initialize_athlete_checkbox(state, "race-b", "same-id", [])

    clear_race_checkbox_state(state, "race-a")

    assert first not in state
    assert state[second] is False


def test_race_switches_keep_selection_and_checkbox_state_isolated():
    state = {}
    synchronize_race_selection(state, "race-a", ["same-name-id-1"])
    synchronize_race_selection(state, "race-b", ["same-name-id-2"])
    update_athlete_selection(state, "race-a", "same-name-id-3", True)

    assert state[selection_key("race-a")] == ["same-name-id-1", "same-name-id-3"]
    assert state[selection_key("race-b")] == ["same-name-id-2"]
    assert athlete_checkbox_key("race-a", "same-name-id-1") != athlete_checkbox_key(
        "race-b", "same-name-id-1"
    )
