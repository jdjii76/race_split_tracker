"""Minimal Streamlit harness for race-roster checkbox state rules."""

import streamlit as st

from split_tracker.roster_selection import (
    athlete_checkbox_key,
    clear_race_checkbox_state,
    initialize_athlete_checkbox,
    set_race_selection,
    synchronize_race_selection,
    update_athlete_selection,
)

ATHLETES = ("a1", "a2", "a3")
PERSISTED = {"race-a": ["a1"], "race-b": ["a2"]}


def changed(race_id: str, athlete_id: str) -> None:
    key = athlete_checkbox_key(race_id, athlete_id)
    update_athlete_selection(
        st.session_state, race_id, athlete_id, st.session_state[key]
    )


race_id = st.selectbox("Race", ["race-a", "race-b"], key="test_race")
persisted = st.session_state.get(f"test_persisted:{race_id}", PERSISTED[race_id])
selected = synchronize_race_selection(st.session_state, race_id, persisted)

if st.button("Select All"):
    set_race_selection(st.session_state, race_id, ATHLETES)
    clear_race_checkbox_state(st.session_state, race_id)
    st.rerun()
if st.button("Clear"):
    set_race_selection(st.session_state, race_id, [])
    clear_race_checkbox_state(st.session_state, race_id)
    st.rerun()
if st.button("Reload Saved Race Roster"):
    set_race_selection(st.session_state, race_id, persisted, saved=True)
    clear_race_checkbox_state(st.session_state, race_id)
    st.rerun()

selected = st.session_state.get(f"race_roster_selection:{race_id}", selected)
for athlete_id in ATHLETES:
    key = initialize_athlete_checkbox(st.session_state, race_id, athlete_id, selected)
    st.checkbox(athlete_id, key=key, on_change=changed, args=(race_id, athlete_id))
