# Isolated Live Timing Development

## Protected prototype checkpoint

- `main` is the protected, coach-tested prototype branch.
- The annotated `prototype-v1` tag identifies the prototype immediately before
  live multi-user timing development.
- Do not merge experimental live timing work directly into `main`.
- `feature/live-multi-user-timing` is the isolated development branch for the
  next feature phase.

The development Streamlit application must be configured to deploy from
`feature/live-multi-user-timing`. Keep the production prototype deployment on
`main`.

## Separate development services

Create a separate Supabase project for development. Do not point the development
Streamlit deployment at the production database, and do not copy production
database credentials into source files, commits, issue comments, or build logs.

Apply `supabase/sql/development_schema.sql` to the separate development project
through its Supabase SQL Editor. This bootstrap reproduces the schema currently
required by the prototype. It is not an application migration to run against the
existing production project.

Configure the development deployment's `SUPABASE_URL` and `SUPABASE_KEY`
manually in **Streamlit Community Cloud → App settings → Secrets**. Use the
development project's publishable/anon key; never place a service-role key in a
Streamlit client application. For local work, use the ignored
`.streamlit/secrets.toml` file or ignored environment files. Only placeholder
examples such as `.env.example` may be committed.

Example Streamlit secrets structure:

```toml
SUPABASE_URL = "https://your-development-project.supabase.co"
SUPABASE_KEY = "your-development-publishable-key"
```

## Deployment checklist

1. Leave `main` unchanged as the protected coach-tested prototype.
2. Push `feature/live-multi-user-timing` and set it as the development app's
   deployment branch.
3. Create a separate development Supabase project; never reuse the production
   Supabase project or its credentials.
4. Run `supabase/sql/development_schema.sql` manually in the development
   project's SQL Editor.
5. Confirm the required tables and checkpoint-start RPC exist.
6. Create a separate Streamlit Community Cloud app that deploys from
   `feature/live-multi-user-timing`.
7. Add only the development project's URL and publishable key through the
   Streamlit Cloud secrets interface.
8. Confirm the development app reports `Storage: Supabase` before beginning
   multi-user timing work.

The current SQL policies intentionally allow development anon access. They are
not suitable for a public, multi-user deployment and must be replaced by
authenticated owner-based policies in a later phase.

## Phase 4.3A shared live timing

Apply `supabase/migrations/006_shared_live_timing.sql` in the Supabase SQL Editor after migrations 001–005. It adds timer attribution, a partial uniqueness constraint for active athlete/checkpoint splits, and the transactional `record_shared_split` RPC. Do not apply the migration from the application and never commit project credentials.

To test manually, run `streamlit run app.py`, open the app in two different browsers (or one normal and one private window), select the same persisted meet/race in both, and enter a different **Timer / display name** in each. Start or recover the active race session and record a split in either browser. The other browser should show it within approximately two seconds. Undoing a split is synchronized on the same polling cycle. Disconnect Supabase temporarily to verify that a failed tap displays an error and can be tapped again after connectivity returns.

Polling is intentionally limited to one request cycle about every two seconds while an active timing page is open. It is not realtime: displays can lag by one polling interval, each open browser generates periodic database reads, participant names are informational rather than authenticated identities, and temporary network errors remain visible until a later successful synchronization. This prototype's development anon policies are not suitable for a public deployment.

The same two-second polling cycle also runs while a browser is connected to a
ready race session and displays **Waiting for race to start**. Start the shared
session from either browser; the other should enter active timing automatically
without refreshing or reselecting the race. Both displays retain their own timer
names and calculate elapsed time from the first persisted `started_at`. No
additional migration is required for waiting-state start synchronization.

During an active race, athlete button progression is rebuilt on every successful
poll from active `split_events` and the persisted `race_session_checkpoints`
sequence. A split or undo made in either browser should therefore advance or
move back the other browser's **Next** checkpoint within about two seconds,
including for custom checkpoint labels. No additional migration is required.

For multi-browser development testing, expand **Development synchronization
status** on each Live Timing page. The panel reports the browser's timer name,
session ID, poll cycle and timestamp, last successful sync, active event count,
latest event identity/time, local and persisted statuses, and the most recent
error. The poll counter should continue increasing about every two seconds on
every browser, including the starter. A failed read keeps the last good display,
shows a warning, and is retried by the next fragment cycle. Live session and
split reads do not use Streamlit caching. No additional migration is required.
