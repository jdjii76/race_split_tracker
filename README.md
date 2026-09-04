# Race Split Tracker

## Race Day Timer Mode

Provision the shared volunteer account with the `timer` role after applying
`supabase/migrations/024_race_day_timer_role.sql` and
`supabase/migrations/025_timer_race_start.sql`, then apply
`supabase/migrations/026_timer_pack_sync.sql` and
`supabase/migrations/027_awaiting_review_lifecycle.sql`. On sign-in, that account is
routed to **Race Day Timer** instead of the coach application. The volunteer
chooses a ready/running race and checkpoint, then sees only the station name,
authoritative race clock, athlete split buttons, connection state, and a control
to change stations. Setup, analytics, results, athlete progression, race
lifecycle, corrections, and administration remain outside timer navigation.
The volunteer assigned to **Finish Line** is the race starter and receives the
single control that starts the authoritative shared clock; split-station timers
wait for that start and do not receive lifecycle controls.

The timer role can read race-day meet, race, roster, session, checkpoint, and
split data and can insert authoritative split events. It cannot edit meet/race
setup or control the race lifecycle through table policies.

Coach and admin accounts can choose **Time a Checkpoint** from Race Day to use
this same station selection, Pack Mode, synchronization, heartbeat, correction,
and Finish Line start workflow. The choice and station are browser-session state
only; **Change Station** keeps Timing Mode active and **Exit Timing Mode** returns
to the Coach Dashboard without changing the account's persisted role. Apply
`supabase/migrations/033_coach_race_day_timing_mode.sql` so these identities can
call the existing station RPCs while their canonical checkpoint and event
validation remains in force.

Timer stations open directly in **Pack Mode** once selected. The compact capture
grid acknowledges each tap in the browser before synchronization, shows the
three newest captures and their saved/synchronized state, and keeps **Undo Last
Tap** within thumb reach. The durable localStorage queue, UUID event identities,
offline retry, server validation, and append-only correction path are unchanged.
During a connection outage or synchronization error, Pack Mode displays a red
offline warning, the exact locally queued count, and a warning not to close or
refresh the page. Capture remains available. Reconnection automatically retries
the same idempotent queue; **Sync Now** can request the same flush manually, and
the browser warns before leaving while unsynchronized captures remain.
Retries also run when the component reconnects, becomes visible, regains focus,
or is recreated. If a recreated Streamlit session assigns a new device ID, the
component recovers pending events for the same race session and checkpoint by
their original event UUIDs before retrying them.
Timers can switch to Individual Timing when runners are separated.
The Pack grid defaults to **All Athletes** and keeps every card in a stable
position after capture. Captured cards remain visible with a green check,
timestamp, and synchronization state; undo restores the uncaptured appearance
after the existing local cancellation or append-only server correction succeeds.
Timer cards show each athlete as **First Name Last Name**, prefixed by the real
bib number only when one is present.
Checkpoint timers can optionally switch from **Stable Roster** to **Expected
Arrival Order**, which snapshots the order from the preceding checkpoint's
cumulative times. Athletes missing that prior split remain tappable and show a
red missing-checkpoint indicator; captures never reorder the selected view.

Coaches and administrators can use **End Race Timing** to stop live capture
without resolving every athlete. The session enters **AWAITING REVIEW**, retains
all timing and audit events, and permits append-only result corrections before
**Finalize & Publish Results** changes the persisted state to `completed`.
Timer accounts cannot access result management or finalization.
The timer assigned to the persisted **Finish Line** checkpoint is the sole timer
exception: that station can use **End Race Timing** to enter `awaiting_review`.
Mile/checkpoint timers receive no lifecycle action, and all result correction and
finalization permissions remain coach/admin-only.

Completed races now include a coach-only **Manage Results** panel. Coaches can add
missed finishes, DNF/DNS outcomes, optional checkpoint times, and append official
corrections. Corrections become the single result used by history, PR, scoring,
public results, and exports while prior timing/result events remain auditable.
Optional checkpoint times can be entered as cumulative elapsed race-clock times
or as individual segment durations. Cumulative values must increase in race
order, while segment durations need only be positive, so negative splits are
accepted and converted to cumulative times without changing stored history.

The app opens on **Race Day** whenever a valid active meet is available. The
touch-friendly dashboard groups persisted races into Running Now, Up Next, and
Completed, with direct Open Timing, Open Race, and View Results actions. It
refreshes from Supabase every five seconds and uses batched session and roster
count reads, so concurrent races remain isolated by race and session UUID. Race
names beginning with `TEST` receive a display-only test indicator. Use the
compact sidebar control to change meets; the selection is also stored in the
page query parameters so it can be restored after a browser refresh. Meet, race,
roster, and checkpoint administration remains under **Meets & Races** and
**Race Setup**.

Race Split Tracker is a Streamlit web application for coaches to record lap, mile, and checkpoint splits for multiple athletes during track and cross country races.

This prototype focuses on fast race-day data entry, session-state storage, CSV export, and tested timing calculations.

## School Branding Configuration

The immutable default profile is `DEFAULT_SCHOOL_PROFILE` in
`split_tracker/branding.py`. It supplies the KMHS school, program, mascot,
location, application title, and all theme colors. The current colors
(`#243447`, `#F5F7FA`, `#B7791F`, and `#FFFFFF`) are accessible temporary
fallbacks—not claimed official colors—and can be replaced in one configuration
section when approved values are available.

School settings are optional. For each field, Streamlit secrets take precedence
over `SCHOOL_*` environment variables, which take precedence over defaults. A
partial override inherits every unspecified KMHS value. For example:

```toml
# .streamlit/secrets.toml
[school]
school_name = "Kennesaw Mountain High School"
short_name = "KMHS"
program_name = "KMHS Cross Country"
mascot = "Mustangs"
city = "Kennesaw"
state = "Georgia"
primary_color = "#243447" # replace after official approval
secondary_color = "#F5F7FA"
accent_color = "#B7791F"
text_on_primary = "#FFFFFF"
logo_path = "assets/branding/approved_logo.png"
compact_logo_path = "assets/branding/approved_mark.png"
```

Approved PNG, JPG, JPEG, and SVG assets may be placed in `assets/branding/` and
selected with `logo_path` or `compact_logo_path`. Missing, unreadable, or
unsupported assets safely fall back to the KMHS text identity. See
`assets/branding/README.md`; the included SVG is placeholder text, not an
official logo. CSV export names are generated centrally, begin with the configured
school abbreviation, replace unsafe filename characters with underscores, and do
not change exported data.

## In-App School Branding

Apply `supabase/migrations/008_school_branding.sql`, then add an administrator
passcode to Streamlit secrets (never commit the real value):

```toml
[admin]
settings_passcode = "replace-this-value"
```

Open **Settings → School & Branding**, enter the passcode, and edit identity,
colors, header layout, logo visibility, and export branding. The passcode is
compared in memory and authorization lasts only for the current browser session;
it is never logged or saved to Supabase. If the secret is absent, the settings
page explains that editing is disabled while all race-day pages remain available.

The page previews unsaved full and compact headers, a race card, action button,
and uploaded images. **Save Changes** validates required text, six-digit colors,
contrast, and images before saving. **Reset Unsaved Changes** reloads stored
values. **Restore KMHS Defaults** requires confirmation and can retain logo
references; it never deletes Storage objects automatically.

### Supabase Storage setup

Logo bytes are stored in Supabase Storage, never in `school_profiles`:

1. Open the Supabase project and select **Storage**.
2. Create a bucket named `branding`.
3. Choose public access if public logo URLs fit the deployment security model, or
   private access with equivalent authenticated/signed-URL policies.
4. Add narrowly scoped read and upload/update policies for
   `schools/default/*`. The development anon policies in the SQL migrations are
   not suitable authorization for production.
5. Verify the Streamlit deployment's existing publishable credentials can upload
   and read objects; never expose or commit a service-role key.
6. Test with a small PNG file (maximum 5 MB).

Uploads accept matching PNG, JPG, or JPEG extensions and MIME types and use the
safe object paths `schools/default/logo.*` and `schools/default/icon.*`. A profile
row stores only those paths. Configure Storage policies before upload; a missing
bucket, rejected upload, missing row, or branding read failure preserves the prior
profile or activates built-in KMHS defaults without blocking timing.

On Streamlit Community Cloud, configure both the `[admin]` passcode and existing
Supabase values in the deployment's Secrets panel, apply the migration through
Supabase, and create the bucket/policies manually. Branding is loaded once into
session cache, refreshed after save/restore, and is never queried by the live
timing polling loop.

## Current Prototype Features

### Permanent Athlete Roster

Apply `supabase/migrations/008_school_branding.sql` followed by
`supabase/migrations/009_permanent_athletes.sql` before deploying this
version. The migration creates the permanent `athletes` table and adds a nullable
UUID relationship from `race_athletes`, while renaming the former text identity
to `legacy_athlete_id`. Existing race rows are deliberately **not** matched by
name: their snapshot name and legacy identity remain readable, and they can be
linked later through a reviewed administrative backfill.

Use **Athletes** to create, filter, edit, injure, deactivate, graduate, or
reactivate school athletes. Status changes and name edits retain the permanent
UUID. Race Setup's primary **Select Athletes** section uses visible, race-scoped
checkboxes and writes permanent IDs into the race-specific roster while retaining
race-time names and metadata as historical snapshots. The editable race-only
roster remains available in the collapsed **Race-Specific Details / Advanced
Manual Race Roster** section for legacy or guest athletes.

The **Import Athlete Roster** expander on the Athletes page provides a permanent-
roster CSV template, validation preview, duplicate review, and an explicit import
confirmation. Uploading a file never writes data by itself. Required columns are
`first_name` and `last_name`; supported optional columns are `preferred_name`,
`graduation_year`, `gender`, `team_division`, `athlete_number`, `status`, and
`notes`. Coaches can skip possible existing duplicates, update the matched stable
athlete ID, or intentionally create another athlete after reviewing the preview.
Imported athletes are saved through the repository to `public.athletes`, not to a
specific race.

An unchanged race selection updates its existing row rather than recreating it.
Deselection is allowed before timing starts, but is blocked once a race session
has started or split events exist. Live Timing continues to read only
`race_athletes`; it never queries the master roster. The migration also replaces
the authoritative split RPC so both nullable legacy identities and permanent
UUID identities remain synchronized across timer clients.

The migration enables RLS with the same development-only anon policy used by the
prototype. Before production, replace it with authenticated coach policies that
permit the deployed Streamlit credentials to read and write `athletes`; do not
use the development policy as production authorization.

Migration numbering was consolidated after two independently prepared changes
both used version `008`: school branding remains the sole `008`, and the
authoritative permanent-roster schema is `009`. The retired combined
`008_permanent_athlete_roster.sql` must not be applied. If branding migration 008
is already recorded in Supabase, apply only 009. If an earlier athlete draft was
manually applied, run the current idempotent 009 SQL in the SQL Editor to add the
school-profile relationship and authoritative constraints without matching or
deleting legacy race athletes.

After migration 009, apply
`supabase/migrations/010_fix_race_athlete_identity_nullability.sql`. Migration
004 originally made the text identity `NOT NULL`; renaming it in 009 preserved
that constraint. Migration 010 makes the permanent UUID and legacy text identity
individually nullable, requires at least one identity, retains both partial unique
indexes, does not rewrite race or split history, and reloads the PostgREST schema
cache. This allows permanent selections to store only `athlete_id` and legacy
race-only athletes to store only `legacy_athlete_id`.

### Race Setup

- Read-only saved race information with meet, date, category, distance, course, and status
- Primary permanent-team selection with search, filters, visible checkboxes, Select All, Clear, and Save Race Roster
- Race-scoped selection state that reloads persistence unless the coach has explicit unsaved edits
- Saved-athlete removal lock after timing starts, preserving historical race snapshots
- Collapsed race-specific details/manual athlete editor with optional CSV import
- Legacy local meet/race and manual-roster setup when no persisted race is selected
- Internal distance storage in meters
- Checkpoint modes for standard laps, fixed intervals, and custom checkpoints
- Finish checkpoint inclusion even when intervals do not divide the race evenly
- Roster fields for athlete name, bib number, target finish time, optional target pace, and group/category
- Compact review followed by Save Race Setup and Start Race actions
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
- Persisted athlete/checkpoint uniqueness with graceful concurrent-tap handling
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
- Supabase-authoritative shared live-race status, roster, checkpoints, and splits
- Streamlit session state only for browser-local UI and diagnostics
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
│       ├── 003_timing_persistence.sql
│       ├── 004_race_rosters.sql
│       └── 005_race_session_checkpoints.sql
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
│   ├── results.py
│   ├── session_checkpoints.py
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

Supabase is the authoritative persistence backend when valid credentials are present and the required migrations have been applied. Without Supabase credentials, the app falls back to the existing local/in-memory behavior and warns that timing-session data is temporary.

Create a local secrets file from the checked-in template:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml` and place your Supabase project URL and publishable key in the top-level Streamlit secrets format:

```toml
SUPABASE_URL = "https://your-project-id.supabase.com"
SUPABASE_KEY = "your-publishable-key"
```

The loader also supports the earlier nested `[supabase]` secrets format for existing local setups. You can alternatively configure the same values with environment variables:

```bash
export SUPABASE_URL="https://your-project-id.supabase.com"
export SUPABASE_KEY="your-publishable-key"
```

Configuration lookup order is top-level Streamlit secrets, nested Streamlit secrets, then environment variables. Missing Supabase configuration does not crash the application. If Supabase is configured but the client cannot initialize or the schema health check fails, the app reports Supabase as unavailable instead of silently switching to temporary storage.

Do not commit `.streamlit/secrets.toml`, `.env`, service-role keys, database passwords, or any real Supabase credentials.

### Storage Modes

| Data | Supabase mode | Fallback mode |
| --- | --- | --- |
| Meet details entered in Race Setup | Persistent in `meets` | Existing local/in-memory behavior |
| Race setup | Persistent in `races` | Existing local/in-memory behavior |
| Rosters | Persistent in `race_athletes` by `race_id` | Current race-scoped fallback behavior |
| Race sessions | Persistent in `race_sessions` | Temporary in-memory repository |
| Checkpoint snapshots | Persistent in `race_session_checkpoints` | Temporary in-memory repository |
| Timing records | Persistent in `split_events` | Temporary in-memory repository |
| Results | Persistent reconstruction from roster, session snapshot, and split events | Temporary reconstruction from active repository state |

The sidebar storage indicator shows `Storage: Supabase` when Supabase is active, `Storage: Temporary in-memory storage` when credentials are missing, or a Supabase-unavailable error if configured storage cannot initialize. Local and Supabase datasets are separate; enabling Supabase does not automatically upload local fallback data.


## Phase 1 Persistence Architecture

Phase 1 adds meet/race/template persistence, race-scoped roster persistence, and live timing-session persistence while preserving the existing Streamlit workflow. Streamlit pages use a repository abstraction instead of directly querying Supabase.

Repository components:

- `RaceRepository`: protocol for meet, race, roster, timing-session, split-event, and template operations.
- `InMemoryRaceRepository`: temporary fallback used when Supabase credentials are missing.
- `SupabaseRaceRepository`: Supabase-backed implementation for meet/race/template setup metadata, race rosters, race sessions, and split events.
- Repository factory: uses Supabase only when configuration is valid and a client can be created. If configuration is missing, it clearly reports temporary storage. If Supabase is configured but unavailable, it reports an error instead of silently falling back.

With Supabase active, the repository persists:

- Meets
- Races
- Meet templates
- Template race definitions
- Race-specific athlete rosters
- Race timing sessions
- Race-session checkpoint snapshots
- Split tap events used to reconstruct live timing and Results views

The app does **not** persist authentication data, user ownership, parent views, public sharing, realtime subscriptions, or generated export files.

## Database Schema

The ordered files in `supabase/migrations/` are the **only authoritative
production schema history**. Apply every file in numeric order; do not use the
bootstrap/reference SQL files as substitutes for the migration chain.

The initial migration, `supabase/migrations/001_initial_schema.sql`, creates:

- `meets`
- `races`
- `meet_templates`
- `template_races`

The migration uses UUID primary keys, UTC timestamps, foreign keys, status check constraints, distance checks, and indexes for meet dates, seasons, race ordering, and template race ordering. Row Level Security is enabled on all four tables. Additional phase migrations add live timing and race roster tables.

> **Development-only RLS warning:** the migration includes clearly marked development-only policies that allow the publishable/anon role to read and write these tables. Replace these policies with authenticated owner-based policies before public deployment or storing real athlete data. Never use service-role keys in the client app.

### Supabase Migration Runbook

Apply migrations manually in the Supabase SQL Editor in this order:

1. `supabase/migrations/001_initial_schema.sql`
2. `supabase/migrations/003_timing_persistence.sql`
3. `supabase/migrations/004_race_rosters.sql`
4. `supabase/migrations/005_race_session_checkpoints.sql`
5. `supabase/migrations/006_shared_live_timing.sql`
6. `supabase/migrations/007_fast_validated_split_rpc.sql`
7. `supabase/migrations/008_school_branding.sql`
8. `supabase/migrations/009_permanent_athletes.sql`
9. `supabase/migrations/010_fix_race_athlete_identity_nullability.sql`
10. `supabase/migrations/011_atomic_active_race_session.sql`
11. `supabase/migrations/012_server_authoritative_split_timing.sql`
12. `supabase/migrations/013_server_authoritative_race_lifecycle.sql`
13. `supabase/migrations/014_safe_athlete_archive.sql`
14. `supabase/migrations/015_live_timing_corrections.sql`
15. `supabase/migrations/016_race_finalization_outcomes.sql`
16. `supabase/migrations/017_secure_coach_and_spectator_access.sql`
17. `supabase/migrations/018_school_sponsors.sql`

There is no `002` migration file; retain that historical numbering gap. Every
present migration version is unique. Migration `008_school_branding.sql` must
precede `009_permanent_athletes.sql` because permanent athletes reference
`school_profiles`. Migration `010` then reconciles permanent UUID and preserved
legacy text identities without matching or updating rows by athlete name.

An obsolete expanded file formerly named
`008_permanent_athlete_roster.sql` duplicated both branding and permanent-roster
work and shared version `008`. It is intentionally not part of the canonical
chain. If that SQL was manually run in an existing development project, do not
drop or recreate its objects and do not remove version `008` from Supabase's
migration history. Continue with the canonical `009` and `010` migrations as
needed: their guarded DDL preserves existing rows and identity values. If the
Supabase migration-history table already records `008`, treat it as the branding
step and verify the branding table before continuing rather than rerunning a
destructive rollback.

After running the chain, confirm these tables exist: `meets`, `races`,
`meet_templates`, `template_races`, `race_sessions`, `split_events`,
`race_athletes`, `race_session_checkpoints`, `school_profiles`, and `athletes`.
Also confirm the `create_started_race_session_with_checkpoints`,
`get_or_create_active_race_session`, `record_shared_split`, and
`transition_race_session` RPC functions exist. Migration `011` preserves terminal history while enforcing at most one
`ready`, `running`, or `paused` session per race. Apply that complete file to an
existing development project after migration `010`; do not edit the migration
history table manually.

Migration `012` replaces `record_shared_split(jsonb)` so PostgreSQL assigns the
official split timestamp, elapsed time, and event order. Apply it after `011`
and before deploying Python code that calls the reduced authoritative RPC
payload.

Migration `013` adds `transition_race_session(uuid, text)`. Apply it after `012`
and before deploying Python code that performs persisted Pause, Resume, End, or
Cancel actions. The RPC locks the session row, validates the state transition,
and derives lifecycle timestamps and elapsed offsets from PostgreSQL time.

Migration `014` adds the `archived` permanent-athlete status and the atomic
`delete_unused_athlete(uuid)` RPC. Apply the complete file after `013` in the
Supabase SQL Editor before deploying the athlete-removal UI. The RPC refuses to
delete a UUID referenced by `race_athletes`; the existing restrictive foreign
key remains a database-level backstop against concurrent history creation.

Migration `015` keeps corrected split rows for audit, adds correction metadata,
and provides atomic `invalidate_split_event` and `record_manual_split` RPCs.
Apply it after `014` before deploying the Live Timing mistake-recovery UI.

Migration `016` adds race-session athlete outcomes and locked DNF, finalization,
and reopen operations. Apply it after `015` before deploying the Finish Race
workflow. It preserves existing sessions and split/correction history.

Migration `017` replaces prototype anonymous-write policies with explicit
`coach`/`admin` roles in `app_users`, protects mutation RPCs with both grants and
`auth.uid()` role checks, and exposes privacy-limited spectator views. Apply it
after `016` before sharing spectator links publicly. It changes authorization
only and does not rewrite race history.

Migration `018` adds the school-scoped sponsor table, the active-only public
spectator sponsor view, and policies for the existing public `branding` Storage
bucket. Apply it after `017`. Sponsor metadata writes and logo uploads require
the `admin` role; anonymous clients can read only active public sponsor metadata
and public branding objects.

## Read-only Spectator Live View

Race Day cards now expose a **Share Live View** link using stable race and, when
available, race-session UUID query parameters. A fresh browser opens the
dedicated `/live-race` route with hidden coach navigation. That route uses a
capability-limited read adapter and the same persisted checkpoint/event
projection and final-results ranking as coach pages. It displays only race and
meet names, race distance/status, athlete display names/team, public split
times, progress, finish status, and final place; internal IDs, correction
metadata, athlete notes, and contact or administrative data are not rendered.

Active and paused spectator views refresh every five seconds and query only the
target race, resolved session, roster, checkpoint snapshot, active events, and
session outcomes. A prominent spectator race clock uses the session's persisted
start timestamp, lifecycle status, and elapsed offset. While running, it advances
locally in each browser between those existing five-second reads; paused,
awaiting-review, and completed clocks remain frozen, with no per-second database
writes or reads. Migration `017` limits anonymous access to privacy-safe public
views and public school branding. Anonymous users receive no protected-table
writes and no mutation RPC execution.

For a directly shareable parent link, configure the deployed Streamlit origin in
Streamlit Cloud Secrets (no trailing slash is required):

```toml
PUBLIC_APP_URL = "https://kmhs-race-timer.streamlit.app"
```

`PUBLIC_APP_URL` may also be supplied as an environment variable. The URL
builder removes trailing slashes and URL-encodes race identifiers. When it is
not configured, local development falls back to `http://localhost:8501`; that
fallback is for local testing and must not be sent to parents. Race Day shares
a race-only URL so one link works before the session exists and continues to
resolve the active/latest session through start, timing, finish, and reopen.

### Provision the first administrator

1. Apply migrations through `017_secure_coach_and_spectator_access.sql`.
2. In **Supabase Dashboard → Authentication → Users**, create the administrator
   with email/password and copy the generated user UUID.
3. In Supabase SQL Editor (which uses the trusted administrative context), run:
   `insert into public.app_users (user_id, role) values ('<USER_UUID>', 'admin');`
4. Sign in through the app's **Coach Sign In** page. Create subsequent users in
   Supabase Auth and assign `coach` or `admin` in `app_users`.

Coaches can configure and time races but permanent-athlete creation/editing,
archive/restore/delete, and branding remain admin-only. The former local
branding settings passcode is no longer used as an authorization gate;
Supabase Auth plus the persisted `admin` role is authoritative.

### Adding Sponsors

1. Apply `supabase/migrations/018_school_sponsors.sql` after migration `017`.
2. Sign in as an administrator and open **School & Branding**.
3. Expand **Add Sponsor**, enter the sponsor name, optionally enter an `http://`
   or `https://` website, set its display order and active state, and upload a
   PNG, JPEG, or WebP logo.
4. Save the sponsor. Use its edit panel to replace the logo, change details,
   activate/deactivate, reorder, or permanently delete it.

Logos reuse the public `branding` bucket at
`sponsors/{school_profile_id}/{sponsor_id}/logo.{extension}`; image bytes are
never stored in PostgreSQL. Active sponsors automatically appear below the
Parent Live Race content. With multiple sponsors, a self-contained browser
component rotates them every six seconds; it performs no Streamlit rerun, sleep,
poll, Supabase query, or race-state write for each transition.

`supabase/sql/development_schema.sql` is a convenience snapshot for bootstrapping
an empty, isolated development project. `database/migrations/001_initial_schema.sql`
is a retained legacy copy of the initial schema. Neither is an independently
maintained migration history; production and upgrades must use
`supabase/migrations/`.

## Race Day Dashboard, Meet Management, and Templates

Race Day is the primary landing page. It reads persisted race sessions and race
roster counts in batches, highlights every simultaneously running race, and
routes directly to existing Live Timing, Race Setup, or Results pages using the
selected race/session UUIDs. Meets & Races lets coaches create, list, open, edit,
archive, and safely delete draft meets. Opening a meet there shows its race list,
where coaches can add, edit, duplicate, archive, delete draft races, reorder races
by display order, and open a saved race in the Race Setup workflow.

The Templates section includes an idempotently seeded default XC meet template containing Boys JV, Girls JV, Boys Varsity, and Girls Varsity races. Each default XC race is 5000 meters. Coaches can create and edit custom templates, archive templates, and create a new meet from a template without generating timing data or results.

When Supabase configuration is missing, the dashboard still works with temporary in-memory storage and displays a warning that meet data resets when the session ends.


## Safe Permanent Athlete Removal

The Athletes page shows active athletes by default and provides explicit Edit
and removal actions. Athletes without a `race_athletes` UUID reference may be
permanently deleted after confirmation. Athletes with any race history can only
be archived, which retains the permanent UUID and every race snapshot and split
while excluding the athlete from normal future-race selection. The Archived
status filter exposes archived records and Restore returns the same row and UUID
to active status. An archived athlete already saved on an existing race remains
visible there and is never removed automatically.

## Race-Scoped Rosters

The `supabase/migrations/004_race_rosters.sql` migration adds `race_athletes`, which stores one roster per persisted race. Each row is keyed to `race_id`, so duplicate bib numbers are allowed across different races but remain unique within the same race when entered. The roster stores athlete name, bib number, gender, grade, team, target finish time, target pace, group/category, display order, and active status.

### Applying the Roster Migration

1. Apply `supabase/migrations/001_initial_schema.sql` first if it has not already been applied.
2. Apply `supabase/migrations/003_timing_persistence.sql` if live timing persistence is enabled.
3. Open your Supabase project.
4. Go to **SQL Editor**.
5. Open `supabase/migrations/004_race_rosters.sql` locally.
6. Copy the full SQL into the Supabase SQL Editor.
7. Run the script.
8. Confirm the `race_athletes` table exists, RLS is enabled, and indexes exist for race roster ordering and active roster lookup.

> **Development-only RLS warning:** the roster migration includes anon read/write policies for prototype development. Replace them with authenticated owner-based policies before public deployment or storing real athlete data.

When switching saved races, the app saves the prior race roster to the race-scoped cache/repository, loads the new race's roster by `race_id`, and clears transient timing state for the previous race. Live Timing uses only the roster loaded for the selected race.

## Persistent Live Timing

### Mistake Recovery

Live Timing keeps normal athlete buttons unchanged and places recovery tools in
a separate Timing Controls section. Undo Last Split and Correct Split atomically
invalidate an exact split-event UUID scoped to the active race-session UUID;
the original row remains stored. Add Missed Split accepts an explicit elapsed
race-clock time only for the athlete's next missing checkpoint and records it as
a manual correction. Every correction reloads persisted events and rebuilds the
same authoritative race projection used by normal timing. Recent Activity is
derived from persisted split and correction rows for the current session.

Rapid retries of the same rendered athlete/checkpoint action reuse a request
UUID, while the database's active athlete/checkpoint uniqueness rule rejects a
competing duplicate. There is no broad debounce delay, so different athletes
finishing close together remain unaffected.

### Finish Race and Final Results

Finish Race summarizes finishers, explicit DNF outcomes, and unresolved
athletes. Every active roster athlete must either have an authoritative finish
event or a session-scoped DNF outcome before the guarded finalization RPC can
complete the session. Completed sessions lock ordinary timing and corrections.
Reopen Race reuses the same session in a paused state, retaining splits,
corrections, and DNF records; coaches may then reverse a DNF, correct history,
resume timing, and finish again. Results rank only valid finishers by finish
elapsed time and deterministic event order, then show DNF and unresolved rows
without numerical places. The CSV retains session and athlete UUIDs, elapsed
seconds, statuses, and per-checkpoint values.

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

Assumptions for this phase: athlete IDs come from the selected race roster. If a persisted split references a runner that is no longer in that roster, the event's stored name/bib are used to reconstruct a visible split. Race-session checkpoint snapshots are authoritative for sessions created after `005_race_session_checkpoints.sql`; legacy sessions without snapshots use the documented fallback.



## Session Checkpoint Snapshots

The `supabase/migrations/005_race_session_checkpoints.sql` migration adds immutable checkpoint snapshots for each race session. When a saved race session starts, the app copies the current generated checkpoints into `race_session_checkpoints` before marking the session running. Those snapshot rows are then the authoritative checkpoint source for Live Timing restoration, historical result reconstruction, missing-split detection, finish detection, and CSV exports.

Snapshot fields include race session ID, checkpoint sequence, label, distance in meters, distance unit, optional lap number, checkpoint type, optional source checkpoint reference, finish flag, and created timestamp. A unique `(race_session_id, checkpoint_sequence)` constraint prevents duplicate checkpoint rows during retries or concurrent starts. Deleting a race session cascades to its checkpoint snapshot rows.

### Applying the Checkpoint Snapshot Migration

1. Apply `supabase/migrations/001_initial_schema.sql` if needed.
2. Apply `supabase/migrations/003_timing_persistence.sql` if needed.
3. Apply `supabase/migrations/004_race_rosters.sql` if needed.
4. Open your Supabase project SQL Editor.
5. Copy and run `supabase/migrations/005_race_session_checkpoints.sql`.
6. Confirm the `race_session_checkpoints` table exists with its unique session/sequence constraint, session-order index, RLS enabled, and development-only anon policy.

Legacy sessions created before this migration may not have checkpoint snapshots. To avoid fabricating historical data from a race configuration that may have changed, read-only result paths use an isolated legacy fallback to the current generated checkpoints and clearly warn the coach when that fallback is used. New sessions always create snapshots at start.

## Race History and Reconstructed Results

The Results page can reopen saved race sessions for a selected meet and race. It lists each timing session with status, start/end timestamps, duration, active split count, and finisher count. Selecting a session reconstructs results from the selected race roster, the persisted race-session checkpoint snapshot, and active `split_events`; soft-deleted split events are excluded from normal result calculations.

Result reconstruction reuses the existing split-calculation path so checkpoint segment splits, cumulative times, finish times, and average pace are derived consistently with Live Timing. Athlete name and bib snapshots stored on split events are used when an event references an athlete that is no longer present in the current race roster.

Result statuses are:

- **Finished**: the athlete has an active split at the finish checkpoint.
- **In Progress**: the session is still active and the athlete has at least one partial split.
- **DNF**: the session is completed/cancelled and the athlete has partial splits but no finish.
- **DNS**: the athlete has no active split events in the selected session.

The CSV download on Results exports the selected race session with stable columns for meet, race, session ID, athlete details, checkpoint split/cumulative times, finish time, average pace, overall place, gender place, category place, and status.

## Supabase Activation Verification

Manual project setup:

1. Create or open a Supabase project.
2. Open the Supabase SQL Editor.
3. Apply migrations in the order listed in the Supabase Migration Runbook.
4. Obtain the project URL and development publishable key.
5. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
6. Fill in `SUPABASE_URL` and `SUPABASE_KEY` with local development credentials.
7. Restart Streamlit with `streamlit run app.py` and confirm the sidebar shows `Storage: Supabase`.

Manual application workflow:

1. Create a meet.
2. Add races and checkpoint configuration.
3. Add a race roster.
4. Start a race session.
5. Record several splits.
6. Stop and restart Streamlit.
7. Reopen the meet and race.
8. Confirm the race session, checkpoint snapshot, and timing records remain.
9. Change the original race setup.
10. Confirm the old session still uses its frozen checkpoint snapshot.
11. Start a new session and confirm it uses the updated setup.

Database inspection queries:

```sql
select id, name, meet_date, status from public.meets order by created_at desc;
select id, meet_id, name, distance_meters, display_order from public.races order by meet_id, display_order;
select race_id, athlete_id, name, bib_number, display_order from public.race_athletes order by race_id, display_order;
select id, race_id, status, started_at, ended_at from public.race_sessions order by created_at desc;
select race_session_id, checkpoint_sequence, label, distance_meters, is_finish from public.race_session_checkpoints order by race_session_id, checkpoint_sequence;
select race_session_id, athlete_id, checkpoint_number, elapsed_seconds, event_order, is_deleted from public.split_events order by race_session_id, event_order;
```

## Known Limitations and Next Phases

Known limitations:

- Roster libraries/shared athlete management are not implemented yet; rosters are persisted only as race-specific rosters.
- Non-selected direct-setup races remain session-state only; saved race rosters, race sessions, race-session checkpoint snapshots, split tap events, reconstructed race history, and selected-session CSV exports are available after applying `003_timing_persistence.sql`, `004_race_rosters.sql`, and `005_race_session_checkpoints.sql`.
- No authentication, owner-based authorization, public sharing, parent/spectator views, realtime subscriptions, or crash recovery exists yet.
- Development-only RLS policies must be replaced before real deployment.

Recommended next task: add authenticated owner-based policies and backfill/verify checkpoint snapshots for any important legacy sessions before expanding roster-library or athlete-management workflows.


## Deletion and Cleanup Behavior

Deletion follows the ownership hierarchy `meet -> races -> race_athletes` and `meet -> races -> race_sessions -> split_events`. The existing database foreign keys already use `on delete cascade` for those relationships, so no additional migration is required for this deletion phase.

Supported destructive actions:

- **Delete race session** from Results: deletes one selected `race_sessions` row and its `split_events`; it does not delete the race or roster.
- **Delete race** from Meet Dashboard: deletes one race plus its roster rows, timing sessions, and split events; it does not delete the parent meet or sibling races.
- **Delete meet** from Meet Dashboard: deletes one meet plus its races, race rosters, timing sessions, and split events; it does not delete meet templates or template races.
- **Clear selected race roster** from Race Setup: deletes only `race_athletes` rows for the selected race and leaves race sessions/splits intact. The UI warns when timing sessions already exist.
- **Development/Admin cleanup** from Meet Dashboard: hidden unless `RACE_SPLIT_TRACKER_ENABLE_DEV_CLEANUP=true`; requires typing `DELETE TEST DATA`; can remove timing data, race rosters, meets/races, or all application test data while preserving templates, template races, schema objects, migrations, and Supabase configuration.

Meet, race, session, roster, and cleanup actions all require explicit typed confirmation. After a successful deletion, Streamlit session-state selections and race-specific caches are cleared so deleted records are not shown until a manual refresh.

## Running the App

Start the Streamlit app with:

```bash
streamlit run app.py
```

### Two-browser shared-timing acceptance test

1. Open the app in a normal window and an incognito/private window.
2. Select the same meet and race in both windows; confirm the displayed race
   session IDs match exactly, then enter a different timer name in each.
3. Start in Window 1. Within one two-second poll, confirm Window 2 shows
   `running` and the same persisted start timestamp without a manual refresh.
4. Tap an athlete in Window 1. Confirm both split boards show the event and both
   athlete buttons advance to the same next checkpoint.
5. Tap a different athlete in Window 2 and confirm both boards converge.
6. Refresh either browser and confirm the status, official elapsed clock,
   athlete progress, and results reconstruct from Supabase.
7. Tap the same athlete/checkpoint nearly simultaneously in both windows.
   Confirm only one event exists and the other client reloads shared progress.
8. Pause, resume, and end in one window, confirming the other window follows
   each persisted status transition.

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

1. Open the Race Setup page.
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

## Live timing responsiveness

Live Timing uses a race-day focus layout: the authoritative race clock and a
compact synchronization indicator stay above a searchable, touch-friendly
athlete grid. **Stable** button order preserves race-roster positions by
default; optional Expected Arrival and Race Order views consume the same
projected race state. Finished athletes move to a collapsed summary while
remaining visible on the progress-ranked Live Race Board. End, undo, reset, and
development diagnostics are secondary so they do not compete with split taps.

Successful athlete taps use one concurrency-safe Supabase RPC and immediately
replay its returned event into the browser's persisted-state projection. The
two-second fragment poll remains the authoritative cross-browser reconciliation
path; conflicts and validation failures force an immediate reload instead.

Streamlit's native buttons still process widget events serially and each click
causes a fragment rerun. The timing controls are isolated in the existing live
fragment and avoid a full application rerun, but taps that arrive while the
browser is submitting the previous widget event cannot be guaranteed at
sub-second spacing. The isolated button surface is the intended seam for a
small queued custom component if field measurements require simultaneous input.

### Live timing mistake recovery

Live Timing includes append-only Undo, wrong-athlete reassignment, missed-split entry,
and correction history. Corrections are persisted in the shared race event stream; the
original tap remains in the audit trail while coach, live-board, and spectator projections
ignore events superseded by a void action. Completed races must be reopened before timing
history can be corrected.

### Finish, review, finalize, and share

When all rostered runners have either finished or been marked DNF, **Finish Race** pauses
the authoritative clock and opens a provisional results review. Coaches can inspect place,
finish time, average pace, and checkpoint splits, return to Live Timing for append-only
corrections, and then choose **Finalize & Publish Results**. Finalization locks the session,
retains it in race history, changes the public parent page from **LIVE** to **FINAL**, and
enables CSV, printable HTML, team-summary, and share-link output from Results.
# Race-day timing modes

## Normal Timing

Use the standard athlete buttons when runners are separated. Each tap is validated by the shared race session and immediately becomes an authoritative split.

## Pack Mode

Use **Pack Mode** when several runners approach the same checkpoint together:

1. Choose the checkpoint and enter Pack Mode.
2. Rapidly tap athletes in crossing order; buttons acknowledge taps entirely in the browser, without waiting for a Streamlit rerun.
3. Watch the captured/queued/synchronized counters and the chronological capture strip.
4. Use **Undo Last Pack Tap** immediately after a mistake. Pending taps are cancelled locally; synchronized taps use the normal append-only void workflow.
5. Exit when the pack clears. If synchronization is outstanding, remain and retry or exit knowing the browser queue is preserved.
6. Use **Recent Activity** for later corrections exactly as with normal timing.

"Captured locally" means the tap and its UTC/monotonic timing metadata are durable in browser `localStorage`; it is not yet visible to other devices. "Synchronized" means the idempotent batch RPC accepted it into canonical `split_events`. Only canonical active events projected by `project_race_state()` are authoritative race results and visible to coaches and spectators.

At entry the component estimates device-clock offset from a reference UTC value supplied by the app. Offsets up to ten seconds are applied to capture UTC while preserving `performance.now()` and capture sequence for ordering; a warning is shown above two seconds, and larger corrections are not silently applied. Network failure never blocks taps: queued events remain namespaced by race session, checkpoint, and device, survive refresh, and retry automatically when connectivity returns.

The capture grid uses direct browser event handlers and a 500 ms batch debounce. It therefore accepts a five- or twenty-runner sequence without a Python round trip between taps; database synchronization occurs after capture and preserves capture timestamp/sequence ordering.

Pack Mode opens in **Expected Arrival Order** by default. For checkpoints after the first,
athletes with a previous split are ordered by that cumulative time, ties retain roster order,
and athletes missing the previous split remain selectable at the end with a visible warning.
The order is snapshotted when the component loads and remains fixed through captures,
synchronization, and rerenders. Timers can switch to **Stable Roster** at any time; both modes
use the same name, optional bib, captured timestamp, and synchronization card treatment.
Missing intermediate checkpoints do not discard later captures: each split remains attached
to its persisted checkpoint, and Expected Arrival cards identify both the missing previous
checkpoint and the athlete's latest available checkpoint. Coaches can fill the missing split
later through the existing append-only correction workflow.

Races may optionally have a scheduled UTC start, entered to any minute, in **Meets & Races**. Scheduled races display
as **Upcoming** until five minutes before that time and **Ready** inside the five-minute window;
this is computed display state and never starts the race clock. Finish Line can open while
the race is Upcoming. Inside the Ready window, every station can load its roster and prepare
Pack Mode, but capture remains locked until Finish Line uses the existing manual **Start Race**
control. Unscheduled races continue to use
their existing persisted readiness and manual-start workflow.
Apply `supabase/migrations/029_prepare_race_session.sql` so timer accounts can create the
shared Ready session and checkpoint snapshot without starting the clock or receiving direct
race-session write permission.
Apply `supabase/migrations/030_timer_pack_undo.sql` to bind each timer device to its selected
session checkpoint. This enables synchronized **Undo Last Tap** only for that device's own
Pack Mode event and appends a `split_voided` audit event; it grants no direct split updates,
manual result editing, or access to the coach/admin correction RPC.
Apply `supabase/migrations/031_append_only_checkpoint_index.sql` to replace the legacy
one-row-per-checkpoint unique index with a non-unique lookup index. RPC validation continues
to enforce logical split rules while allowing the original, its `split_voided` audit row, and
an optional replacement to coexist in append-only history.

Apply `supabase/migrations/032_timer_station_health.sql` for the race-day station monitor.
The migration stores only a throttled station heartbeat; capture totals, latest athlete, and
last successful synchronization remain derived from existing append-only Pack events. Timer
devices may heartbeat only an exact station assignment, have no direct table access, and
cannot read the coach/admin monitor RPC. The Timer landing card summarizes the assigned race,
station, roster, clock, and local synchronization state, while the Race Day coach dashboard
classifies checked-in stations as Active, Waiting, or Offline.

## Athlete Progression

Administrators can choose **Athletes → View Profile** to open the protected athlete profile, or use **Team Progress** for season-wide comparison. Profiles include archived athletes when opened from the archived roster filter and are not added to spectator routes.

Only completed race sessions count as history. DNF entries remain visible but are not timed performances; provisional or unfinished sessions do not affect metrics. History is rebuilt from canonical split events, so an append-only void/replacement correction immediately changes the profile while the original remains in the audit history.

Metrics are derived, not stored. A season PR is the fastest finish within one race-date year and distance. Best pace is the lowest final-time-per-mile value. Improvement is the first chronological finish minus the fastest finish for the same season and distance. Course bests group only by permanent course UUID and distance. For segment consistency, at most 3% spread is **Even**; otherwise a 3% later-half slowdown is **Positive Split**, a 3% speed-up is **Negative Split**, and other patterns are **Variable**. Two segments are required.

Team Progress uses existing gender and Varsity/JV/Swing team-division values. Apply `supabase/migrations/021_athlete_progression_courses.sql`, then restart Streamlit. The additive migration creates protected courses, adds nullable `races.course_id`, and adds history indexes. Existing races remain functional. Courses are created and linked in **Meets & Races**.

## Coach Post-Race Analytics

**Coach Analytics** is a protected, read-only view available from a completed race card and from Final Results. It is authoritative only after **Finalize & Publish Results**. The dashboard derives finishers, distance-specific PRs, Top 7, 1–5 and 1–7 spreads, Top-5 compression, early/late pace, negative splits, late fades, and previous-race comparisons from finalized canonical results; it stores no analytics rows.

A PR requires a faster prior finalized, non-test result for the same athlete and distance; a first result is labeled **First recorded**, DNF cannot PR, and the current session is excluded. Early pace is the first valid positive-distance segment and late pace is the final valid positive-distance segment, each normalized to seconds per mile. Pace change is late minus early: negative is a negative split and positive is a fade. These are descriptive measurements and do not infer strategy or cause.

Top 7 eligibility follows the actual selected race roster. BV and GV races therefore remain separate, while a Swing athlete can rank in the varsity or JV race they actually ran without changing their permanent classification. Spreads use team-ranked finishers. Missing or invalid checkpoints are never treated as zero: athletes remain in finish analytics but are excluded from pace metrics unless at least two measurable segments exist.

The prior comparison is the most recent earlier finalized, non-test session with the same distance and normalized race category (falling back to race name). Different distances and categories are not compared. If none exists, the page reports that explicitly. Append-only corrections are resolved by the existing active-event projection, so only replacements affect analytics while the audit trail stays intact. No database migration is required for Coach Analytics.

### Manual Coach Analytics test

1. Create and finalize Race A at 5K with realistic checkpoint splits.
2. Create Race B with the same category, distance, and at least seven finishers.
3. Include a PR, a negative split, a late fade, and an athlete missing an intermediate checkpoint; finalize Race B.
4. Open **Coach Analytics** from Race B and verify PR amount, highlights, Top 7, both spreads, Top-5 gaps, pace profile, Race A comparison, and athlete table.
5. Confirm the missing-split athlete remains in finish metrics but not pace metrics.
6. In a third race, correct a result during provisional review, finalize, and verify analytics use the replacement while Recent Actions/audit history retains the original and void.

## Manual post-race result check

1. Create or locate a completed test race, then open **Results** and select its completed session.
2. Expand **Manage Results**, choose an athlete with no result, select **Finished**, enter `22:15.4`, and save.
3. Confirm final results and the athlete profile/history each show the race once and the race remains completed with its finalized timestamp.
4. Reopen **Manage Results**, select the athlete, change the time to `22:13.92`, choose **Official**, and enter `Official meet results`.
5. Check the confirmation statement, save, and verify final results and athlete history show only `22:13.92`.
6. Expand **Result History** and verify `22:15.4` is superseded; for a live-timed original, verify the original timing event is also identified as preserved.
7. Open the parent results link and verify only `22:13.92` is public.
8. Repeat with an athlete who has no timing events and a **DNF** result; verify no finish time or place is assigned.
9. Correct an athlete whose original result came from live timing and verify the live clock/session is not reopened.
