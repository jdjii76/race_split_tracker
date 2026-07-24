# AGENTS.md

## Project Overview
Race Split Tracker is a Streamlit web application for coaches to record and analyze lap, mile, and checkpoint splits for multiple athletes during track and cross country races.

## Development Guidelines
- Use Python 3.11 or newer.
- Build the app with Streamlit.
- Use `st.Page` and `st.navigation` for multipage navigation.
- Store first-prototype data in Streamlit session state only; do not add persistent storage unless explicitly requested.
- Use `time.perf_counter()` for active race timing.
- Keep calculations separate from the Streamlit interface.
- Prefer small, testable functions for timing, pace, projected finish, split recalculation, and target pace variance logic.
- Optimize the live timing interface for phones and tablets with large touch-friendly controls.

## Suggested Structure
- `app.py`: Streamlit entry point and navigation.
- `split_tracker/calculations.py`: Pure calculation helpers.
- `split_tracker/models.py`: Data models or typed structures.
- `split_tracker/formatting.py`: Time and pace formatting helpers.
- `split_tracker/state.py`: Session-state initialization and mutation helpers.
- `pages/`: Streamlit page renderers used by `st.Page`.
- `tests/`: Automated tests for calculation and state logic.

## Testing
Run automated tests with:

```bash
python -m pytest
```

When practical, also run a syntax check with:

```bash
python -m compileall .
```

## Documentation
Update `README.md` whenever setup steps, run commands, dependencies, or user-facing behavior change.
