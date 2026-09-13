"""Dedicated public, read-only live race page."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
import logging

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from split_tracker.branding import render_school_header
from split_tracker.formatting import format_distance
from split_tracker.spectator import load_spectator_race, spectator_elapsed_seconds, spectator_repository
from split_tracker.sponsors import sponsor_carousel_html

logger = logging.getLogger(__name__)


def _race_clock_html(session, *, now: datetime | None = None) -> str:
    """Build a browser-only ticking clock anchored to authoritative session timing."""
    current = now or datetime.now(timezone.utc)
    status = session.status if session else "ready"
    payload = json.dumps({
        "elapsed": spectator_elapsed_seconds(session, now=current),
        "running": status == "running",
        "status": {
            "paused": "Paused",
            "awaiting_review": "Awaiting Review",
            "completed": "Completed",
            "cancelled": "Completed",
        }.get(status, ""),
        "startedAt": session.started_at.isoformat() if session and session.started_at else None,
    })
    return f"""
    <div class="race-clock" role="timer" aria-live="off">
      <div class="clock-label">Race Time</div>
      <div id="race-time" class="clock-time">--:--</div>
      <div id="clock-state" class="clock-state"></div>
      <div id="started-at" class="started-at"></div>
    </div>
    <style>
      body{{margin:0;color-scheme:light dark;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:CanvasText;background:transparent}}
      .race-clock{{box-sizing:border-box;text-align:center;border:1px solid rgba(128,128,128,.35);border-radius:14px;padding:12px 16px;background:rgba(128,128,128,.08)}}
      .clock-label{{font-size:16px;font-weight:750}}
      .clock-time{{font-size:46px;line-height:1.08;font-weight:850;font-variant-numeric:tabular-nums;letter-spacing:.02em}}
      .clock-state{{font-size:15px;font-weight:750;margin-top:2px}}
      .started-at{{font-size:13px;opacity:.72;margin-top:4px}}
    </style>
    <script>
      const clock = {payload};
      const loadedAt = performance.now();
      const timeNode = document.getElementById("race-time");
      function formatElapsed(value) {{
        const total = Math.max(0, Math.floor(value));
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const seconds = total % 60;
        return hours ? `${{hours}}:${{String(minutes).padStart(2,"0")}}:${{String(seconds).padStart(2,"0")}}`
                     : `${{minutes}}:${{String(seconds).padStart(2,"0")}}`;
      }}
      function renderClock() {{
        const elapsed = clock.elapsed + (clock.running ? (performance.now() - loadedAt) / 1000 : 0);
        timeNode.textContent = formatElapsed(elapsed);
      }}
      document.getElementById("clock-state").textContent = clock.status;
      if (clock.startedAt) {{
        const started = new Date(clock.startedAt).toLocaleTimeString([], {{hour:"numeric",minute:"2-digit",second:"2-digit"}});
        document.getElementById("started-at").textContent = `Started ${{started}}`;
      }}
      if (!clock.running && !clock.startedAt) {{
        document.querySelector(".clock-label").textContent = "Race has not started";
        timeNode.style.display = "none";
      }}
      renderClock();
      if (clock.running) setInterval(renderClock, 250);
    </script>
    """


def _athlete_card_html(index: int, athlete) -> str:
    """Group the public athlete name, authoritative time, and progress."""
    name = escape(athlete.name)
    team = escape(athlete.team)
    checkpoint = escape(athlete.latest_checkpoint)
    next_checkpoint = escape(athlete.next_checkpoint)
    cumulative = escape(athlete.cumulative_time)
    status = escape(athlete.status)
    if athlete.status == "DNF":
        primary = "DNF"
        detail = f"{checkpoint} · {cumulative}"
    elif athlete.status == "Finished":
        primary = cumulative
        detail = "FINISHED"
    else:
        primary = cumulative
        detail = f"{checkpoint} · Next: {next_checkpoint} · {status}"
    team_line = f'<div class="spectator-team">{team}</div>' if team else ""
    return (
        '<div class="spectator-athlete-card">'
        '<div class="spectator-athlete-top">'
        f'<div class="spectator-athlete-name">{index}. {name}</div>'
        f'<div class="spectator-athlete-time">{primary}</div>'
        '</div>'
        f'{team_line}<div class="spectator-athlete-progress">{detail}</div>'
        '</div>'
    )


def _render_sponsors(public_repository) -> None:
    """Sponsor failure is isolated from the higher-priority race display."""
    try:
        sponsors = public_repository.list_active_sponsors()
        carousel = sponsor_carousel_html(sponsors)
    except Exception:
        logger.warning("Sponsor content could not be loaded; continuing with race display.", exc_info=True)
        return
    if carousel:
        components.html(carousel, height=190, scrolling=False)


def _render_race(public_repository, profile, race_id, session_id) -> None:
    st.markdown("""
        <style>
        [data-testid='stSidebar']{display:none;}
        .stApp [data-testid='stMainBlockContainer']{max-width:760px;}
        .spectator-athlete-card{border:1px solid rgba(128,128,128,.35);border-radius:.8rem;padding:.8rem 1rem;margin:.55rem 0;}
        .spectator-athlete-top{display:flex;align-items:baseline;justify-content:space-between;gap:.75rem;}
        .spectator-athlete-name{font-size:1.15rem;font-weight:750;line-height:1.25;min-width:0;}
        .spectator-athlete-time{font-size:1.55rem;font-weight:800;line-height:1;white-space:nowrap;}
        .spectator-athlete-progress{font-size:.95rem;margin-top:.35rem;}
        .spectator-team{font-size:.8rem;opacity:.72;margin-top:.15rem;}
        @media(max-width:430px){.spectator-athlete-card{padding:.72rem .8rem}.spectator-athlete-name{font-size:1.05rem}.spectator-athlete-time{font-size:1.4rem}}
        </style>
        """, unsafe_allow_html=True)
    try:
        view = load_spectator_race(public_repository, race_id=race_id, session_id=session_id)
    except Exception:
        view = None
    if view is None:
        render_school_header(profile, "Live Race")
        st.warning("Race not found.")
        return

    subtitle = view.meet.name if view.meet else profile.program_name
    render_school_header(profile, view.race.name, subtitle=subtitle, compact=True)
    st.header(f"{view.race.name} • {format_distance(view.race.distance_meters)}")
    public_status = "FINAL" if view.session and view.session.status == "completed" else "LIVE"
    st.markdown(f"## {public_status}")
    components.html(_race_clock_html(view.session), height=150, scrolling=False)
    st.caption(f"Last updated: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    if view.session is None:
        st.info("Live results will appear when timing begins.")
        return
    if view.status == "Finished":
        st.subheader("Final Results")
        final = pd.DataFrame([
            {"Place": row["Place"], "Athlete": row["Athlete"], "Final Time": row["Final Time"], "Status": row["Status"]}
            for row in view.final_rows
        ])
        if final.empty:
            st.info("Final results are not available yet.")
        else:
            st.dataframe(final, hide_index=True, use_container_width=True)
        return

    for index, athlete in enumerate(view.athlete_rows, start=1):
        st.markdown(_athlete_card_html(index, athlete), unsafe_allow_html=True)
    st.caption("Live splits and positions are unofficial until the race is completed.")


if hasattr(st, "fragment"):
    _render_race = st.fragment(run_every=5)(_render_race)


def render() -> None:
    """Keep the browser carousel outside the five-second race fragment."""
    profile = st.session_state.school_profile
    repository = st.session_state.get("repository")
    if repository is None:
        render_school_header(profile, "Live Race")
        st.info("Live race data is temporarily unavailable.")
        return
    public_repository = spectator_repository(repository)
    _render_race(
        public_repository, profile, st.query_params.get("spectator_race"),
        st.query_params.get("spectator_session"),
    )
    _render_sponsors(public_repository)
