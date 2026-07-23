# Race Split Tracker

Race Split Tracker is a Streamlit web application for coaches to record lap, mile, and checkpoint splits for multiple athletes during track and cross country races.

This prototype focuses on fast race-day data entry, session-state storage, CSV export, and tested timing calculations.

## Current Prototype Features

### Meet Setup

- Meet name and race name fields
- Course type selector for Track or Cross Country
- Track and cross country race-distance presets with custom meter distances
- Internal distance storage in meters
- Checkpoint modes for standard laps, fixed intervals, and custom checkpoints
- Finish checkpoint inclusion even when intervals do not divide the race evenly
- Editable athlete roster with add/delete rows and paste support through the data editor
- CSV roster import and roster template download
- Roster fields for athlete name, bib number, target finish time, optional target pace, and group/category
- Setup summary before saving
- Clear Setup confirmation and Start Timing navigation
- Validation for required meet/race names, athlete names, duplicate bibs, target-time formats, and at least one athlete

### Live Timing

- Prominent race header with meet, race, distance, status, large clock, and split count
- Race clock based on `time.perf_counter()` with Streamlit-supported fragment refresh when available
- Start, pause, resume, end race, undo last tap, and reset race controls
- Confirmation requirements for end, undo, and reset actions
- Start disabled until setup is valid
- Large athlete buttons suitable for phones and tablets
- Athlete buttons show bib, next checkpoint, latest segment, cumulative time, and target variance when available
- Tap an athlete to record the exact elapsed time
- Automatic calculation of checkpoint, segment split, cumulative time, average pace, projected finish, and target variance
- Two-second duplicate-tap protection with an explicit Record Anyway action
- Finished-athlete handling with reopen controls for corrections
- Live split board sorted by latest checkpoint and cumulative time
- Active/finished filtering and race-complete messaging

### Results

- Table of all recorded splits
- CSV download
- Individual athlete split chart

## Technical Approach

- Python 3.11 or newer
- Streamlit for the web interface
- `st.Page` and `st.navigation` for multipage app navigation
- Streamlit session state for prototype data storage
- `time.perf_counter()` for race timing
- Raw durations stored as decimal seconds
- Distances stored internally in meters
- Separate calculation and formatting logic from Streamlit UI code
- Automated tests for calculation, formatting, and state-management behavior

## Project Structure

```text
race_split_tracker/
├── app.py
├── requirements.txt
├── AGENTS.md
├── README.md
├── pages/
│   ├── __init__.py
│   ├── live_timing.py
│   ├── meet_setup.py
│   └── results.py
├── split_tracker/
│   ├── __init__.py
│   ├── calculations.py
│   ├── formatting.py
│   ├── models.py
│   └── state.py
└── tests/
    ├── test_calculations.py
    ├── test_formatting.py
    └── test_state.py
```

## Installation

Create and activate a virtual environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

If your system uses `python` for Python 3.11 or newer, you can substitute `python` for `python3.11`.

## Running the App

Start the Streamlit app with:

```bash
streamlit run app.py
```

Streamlit will print a local URL that you can open in a browser. For race-day use, open the app on a phone or tablet connected to the same development machine or deployment environment.

## Running Tests

Run the automated test suite with:

```bash
python -m pytest
```

A syntax check can also be run with:

```bash
python -m compileall .
```

## Prototype Workflow

1. Open the Meet Setup page.
2. Enter meet and race details.
3. Add athletes, bib numbers, and optional target paces.
4. Go to the Live Timing page.
5. Start the race clock.
6. Tap athlete buttons as athletes pass each checkpoint.
7. Undo the latest split if needed.
8. End the race.
9. Review results, download CSV data, and inspect individual athlete charts.

## Development Notes

- Keep race calculations deterministic and independent from Streamlit widgets.
- Recalculate derived split fields after editing or deleting results in a future correction workflow.
- Use clear, touch-friendly controls on the Live Timing page.
- Avoid adding database or file persistence during the first prototype unless requested.
