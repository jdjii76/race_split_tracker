"""Predictable Streamlit state synchronization for permanent race rosters."""
from __future__ import annotations


def selection_key(race_id: str) -> str:
    return f"race_roster_selection:{race_id}"


def saved_selection_key(race_id: str) -> str:
    return f"race_roster_saved_selection:{race_id}"


def selection_dirty_key(race_id: str) -> str:
    return f"race_roster_selection_dirty:{race_id}"


def athlete_checkbox_key(race_id: str, athlete_id: str) -> str:
    return f"race_roster_checkbox:{race_id}:{athlete_id}"


def _ordered_unique(values) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def set_race_selection(state, race_id: str, athlete_ids, *, saved: bool = False) -> list[str]:
    """Set one race's selection and synchronize its existing checkbox widgets."""
    selected = _ordered_unique(athlete_ids)
    prior = set(state.get(selection_key(race_id), []))
    known = prior | set(selected) | set(state.get(saved_selection_key(race_id), []))
    state[selection_key(race_id)] = selected
    if saved:
        state[saved_selection_key(race_id)] = list(selected)
    baseline = state.get(saved_selection_key(race_id), [])
    state[selection_dirty_key(race_id)] = selected != list(baseline)
    for athlete_id in known:
        state[athlete_checkbox_key(race_id, athlete_id)] = athlete_id in selected
    return selected


def synchronize_race_selection(state, race_id: str, persisted_ids) -> list[str]:
    """Use persistence unless this race has explicit unsaved local edits."""
    persisted = _ordered_unique(persisted_ids)
    saved_key = saved_selection_key(race_id)
    if saved_key not in state or not state.get(selection_dirty_key(race_id), False):
        set_race_selection(state, race_id, persisted, saved=True)
    return list(state.get(selection_key(race_id), persisted))


def update_athlete_selection(state, race_id: str, athlete_id: str, selected: bool) -> list[str]:
    """Apply one checkbox edit without disturbing hidden/filtered selections."""
    current = list(state.get(selection_key(race_id), []))
    if selected and athlete_id not in current:
        current.append(athlete_id)
    elif not selected:
        current = [value for value in current if value != athlete_id]
    return set_race_selection(state, race_id, current)


def persisted_selection_changed(state, race_id: str, persisted_ids) -> bool:
    """Return whether saved data changed while local unsaved edits exist."""
    return bool(
        state.get(selection_dirty_key(race_id), False)
        and _ordered_unique(persisted_ids) != list(state.get(saved_selection_key(race_id), []))
    )
