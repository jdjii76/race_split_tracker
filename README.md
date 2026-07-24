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
├── supabase/
│   └── migrations/
│       ├── 001_initial_schema.sql
│       └── 003_timing_persistence.sql
├── README.md
├── pages/
│   ├── __init__.py
│   ├── live_timing.py
│   ├── meet_dashboard.py
│   ├── meet_setup.py
│   └── results.py
├── split_tracker/
│   ├── __init__.py
│   ├── calculations.py
│   ├── config.py
│   ├── formatting.py
│   ├── models.py
│   ├── repository.py
│   ├── state.py
│   ├── supabase_client.py
│   └── timing_persistence.py
└── tests/
    ├── test_calculations.py
    ├── test_formatting.py
    ├── test_navigation.py
    ├── test_repository.py
    ├── test_state.py
    └── test_supabase_config.py
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


## Optional Supabase Configuration

Supabase support is currently configuration-only. The app can load Supabase credentials and construct a client when both values are available, but it does not create tables, run migrations, authenticate users, or persist race data yet.

Create a local secrets file from the checked-in template:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml` and place your Supabase project URL and publishable key under the `supabase` section:

```toml
[supabase]
url = "https://your-project-id.supabase.com"
key = "your-publishable-key"
```

You can also configure the same values with environment variables instead of Streamlit secrets:

```bash
export SUPABASE_URL="https://your-project-id.supabase.com"
export SUPABASE_KEY="your-publishable-key"
```

Configuration lookup order is Streamlit secrets first, then environment variables. Missing Supabase configuration does not crash the application; client creation is skipped until both values are present.

Do not commit `.streamlit/secrets.toml`, `.env`, service-role keys, database passwords, or any real Supabase credentials.


## Phase 1 Persistence Architecture

Phase 1 adds meet/race/template persistence for pre-meet planning while preserving the existing session-state timing workflow. Streamlit pages use a repository abstraction instead of directly querying Supabase.

Repository components:

- `RaceRepository`: protocol for meet, race, and template operations.
- `InMemoryRaceRepository`: temporary fallback used when Supabase credentials are missing.
- `SupabaseRaceRepository`: Supabase-backed implementation for meet/race/template setup metadata.
- Repository factory: uses Supabase only when configuration is valid and a client can be created. If configuration is missing, it clearly reports temporary storage. If Supabase is configured but unavailable, it reports an error instead of silently falling back.

Phase 1 persists only:

- Meets
- Races
- Meet templates
- Template race definitions

Phase 1 does **not** persist athletes, checkpoints, live splits, results, crash recovery state, authentication data, parent views, public sharing, or realtime subscriptions.

## Database Schema

The initial schema is in `supabase/migrations/001_initial_schema.sql` and creates:

- `meets`
- `races`
- `meet_templates`
- `template_races`

The migration uses UUID primary keys, UTC timestamps, foreign keys, status check constraints, distance checks, and indexes for meet dates, seasons, race ordering, and template race ordering. Row Level Security is enabled on all four tables.

> **Development-only RLS warning:** the migration includes clearly marked development-only policies that allow the publishable/anon role to read and write these tables. Replace these policies with authenticated owner-based policies before public deployment or storing real athlete data. Never use service-role keys in the client app.

### Running the Supabase Migration

1. Open your Supabase project.
2. Go to **SQL Editor**.
3. Open `supabase/migrations/001_initial_schema.sql` locally.
4. Copy the full SQL into the Supabase SQL Editor.
5. Run the script.
6. Confirm these tables exist in the Table Editor: `meets`, `races`, `meet_templates`, and `template_races`.
7. Confirm indexes exist for `meets.meet_date`, `meets.season`, `races(meet_id, display_order)`, and `template_races(template_id, display_order)`.

## Meet Dashboard and Templates

The Meet Dashboard is the primary landing page. Coaches can create, list, open, edit, archive, and safely delete draft meets. Opening a meet shows its race list, where coaches can add, edit, duplicate, archive, delete draft races, reorder races by display order, and open a saved race in the existing Meet Setup workflow.

The Templates section includes an idempotently seeded default XC meet template containing Boys JV, Girls JV, Boys Varsity, and Girls Varsity races. Each default XC race is 5000 meters. Coaches can create and edit custom templates, archive templates, and create a new meet from a template without generating timing data or results.

When Supabase configuration is missing, the dashboard still works with temporary in-memory storage and displays a warning that meet data resets when the session ends.


## Persistent Live Timing

The `supabase/migrations/003_timing_persistence.sql` migration adds persistent live timing state for selected saved races. It creates:

- `race_sessions`: one timing session per start/restart attempt, with status, start/pause/end timestamps, and an elapsed offset used to restore the race clock without writing every second.
- `split_events`: one persisted event per athlete tap, including athlete identifier, checkpoint number/label, elapsed seconds, deterministic event order, and soft-delete state for undo.

The visible race clock still updates locally from `time.perf_counter()`. Supabase is updated only for lifecycle events such as start, pause, resume, complete/cancel, athlete taps, and undo. Undo marks split events deleted instead of permanently deleting them.

### Applying the Timing Migration

1. Apply `supabase/migrations/001_initial_schema.sql` first if it has not already been applied.
2. Open your Supabase project.
3. Go to **SQL Editor**.
4. Open `supabase/migrations/003_timing_persistence.sql` locally.
5. Copy the full SQL into the Supabase SQL Editor.
6. Run the script.
7. Confirm these tables exist: `race_sessions` and `split_events`.
8. Confirm RLS is enabled and indexes exist for race-session lookup and split-event ordering.

> **Development-only RLS warning:** the timing migration also includes anon read/write policies for prototype development. Replace them with authenticated owner-based policies before public deployment or storing real athlete data.

### Manual Timing Recovery Checklist

1. Open a saved race from the Meet Dashboard.
2. Start timing.
3. Record several athlete taps.
4. Pause the race.
5. Refresh the browser and confirm the race reloads as paused with the correct elapsed time and splits.
6. Resume the race and record more taps.
7. Refresh while running and confirm the running clock and active splits are restored.
8. Undo the latest split.
9. Refresh and confirm the undone split remains excluded.
10. Complete the race.
11. Reopen the app, open the same race, and confirm the completed timing session and splits remain available.

Assumptions for this phase: athlete IDs come from the current roster in session state; if a persisted split references a runner that is no longer in the roster, the event's stored name/bib are used to reconstruct a visible split. Checkpoint persistence is not added yet, so restored split records use the currently loaded race checkpoint configuration.

## Known Limitations and Next Phases

Known limitations:

- Roster libraries are not persisted yet.
- Checkpoint definitions, roster libraries, results exports, and non-selected direct-setup races remain session-state only; saved race sessions and split tap events are persisted after applying `003_timing_persistence.sql`.
- No authentication, owner-based authorization, public sharing, parent/spectator views, realtime subscriptions, or crash recovery exists yet.
- Development-only RLS policies must be replaced before real deployment.

Recommended next task: add authenticated owner-based policies and persist race rosters/checkpoint definitions before persisting live splits.

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
