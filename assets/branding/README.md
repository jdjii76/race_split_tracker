# Branding assets

The included SVG is text-only placeholder artwork and is **not an official school logo**.
Place an approved `.png`, `.jpg`, `.jpeg`, or `.svg` file in this directory, then set
`school.logo_path` and/or `school.compact_logo_path` in `.streamlit/secrets.toml` (or
the corresponding `SCHOOL_LOGO_PATH` environment variable). Logos render at their
natural aspect ratio. Missing, unreadable, and unsupported files use the compact
text identity instead and never prevent the app from starting.
