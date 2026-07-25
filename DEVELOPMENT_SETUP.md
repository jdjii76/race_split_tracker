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
