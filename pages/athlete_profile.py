"""Protected coach athlete progression profile."""
from datetime import date
import altair as alt
import pandas as pd
import streamlit as st
from split_tracker.auth import AuthenticationError, require_admin
from split_tracker.athletes import grade_from_graduation_year
from split_tracker.branding import render_school_header
from split_tracker.formatting import format_distance, format_duration, format_pace
from split_tracker.progression import course_bests, filter_results, get_completed_results, season_summary, split_consistency


def render():
    try: require_admin(st.session_state.get("app_identity"))
    except AuthenticationError as exc: st.error(str(exc)); return
    repo=st.session_state.repository; athlete=repo.get_athlete(st.session_state.get("profile_athlete_id", ""))
    if not athlete: st.warning("Choose View Profile from Athletes."); return
    render_school_header(st.session_state.school_profile, athlete.display_name)
    grade=grade_from_graduation_year(athlete.graduation_year, date.today().year)
    st.caption(" • ".join(x for x in (athlete.gender, athlete.team_division, grade, f"Class of {athlete.graduation_year}" if athlete.graduation_year else "", athlete.status.title()) if x))
    history=get_completed_results(repo, athlete.id)
    seasons=sorted({r.season for r in history if r.season}, reverse=True)
    selected=st.selectbox("Season", [*(str(s) for s in seasons), "All"] if seasons else ["All"])
    season=None if selected == "All" else int(selected)
    scoped=filter_results(history, season=season)
    distances=sorted({r.distance_meters for r in scoped})
    distance=st.selectbox("Distance", distances, format_func=format_distance) if distances else None
    comparable=filter_results(scoped, distance_meters=distance); summary=season_summary(comparable)
    cols=st.columns(6)
    values=[("Season PR",format_duration(summary["season_pr"])),("Best Pace",format_pace(summary["best_pace"])),("Races",str(summary["races"])),("Best Place",str(summary["best_place"] or "—")),("Latest",format_duration(summary["most_recent"].finish_seconds) if summary["most_recent"] else "—"),("Improvement",format_duration(summary["improvement"]))]
    for col,(label,value) in zip(cols,values): col.metric(label,value)
    st.subheader("Progression")
    chart_rows=[{"Date":r.race_date,"Race":f"{r.meet_name} — {r.race_name}","Finish (seconds)":r.finish_seconds} for r in reversed(comparable) if r.status=="Finished"]
    if chart_rows:
        chart=alt.Chart(pd.DataFrame(chart_rows)).mark_line(point=True).encode(x="Date:T",y=alt.Y("Finish (seconds):Q",scale=alt.Scale(reverse=True)),tooltip=["Race","Date","Finish (seconds)"])
        st.altair_chart(chart,use_container_width=True)
    else: st.info("No comparable finished races.")
    st.subheader("Race History")
    for result in scoped:
        with st.expander(f"{result.race_date or 'Unknown date'} • {result.meet_name} — {result.race_name} • {result.status}"):
            st.write(f"**Course:** {result.course_name or 'Unknown'} · **Distance:** {format_distance(result.distance_meters)} · **Time:** {format_duration(result.finish_seconds)} · **Pace:** {format_pace(result.pace_seconds_per_mile)} · **Place:** {result.place or '—'}")
            rows=[]
            for split in result.splits:
                distance_delta=float(split["distance_meters"])-(float(result.splits[len(rows)-1]["distance_meters"]) if rows else 0)
                pace=float(split["segment"])/(distance_delta/1609.344) if distance_delta>0 else None
                rows.append({"Checkpoint":split["label"],"Distance":format_distance(float(split["distance_meters"])),"Cumulative":format_duration(float(split["cumulative"])),"Segment":format_duration(float(split["segment"])),"Segment Pace":format_pace(pace)})
            st.dataframe(rows,hide_index=True,use_container_width=True)
    st.subheader("Course Bests")
    st.dataframe([{"Course":r.course_name,"Distance":format_distance(r.distance_meters),"Best":format_duration(r.finish_seconds),"Date":r.race_date} for r in course_bests(scoped)],hide_index=True,use_container_width=True)
    st.subheader("Split Consistency")
    latest=next((r for r in scoped if r.splits),None); analytics=split_consistency([s["segment"] for s in latest.splits]) if latest else None
    if not analytics: st.info("Not enough split data")
    else: st.write(f"**{analytics['label']}** · Average {format_duration(analytics['average'])} · Fastest {format_duration(analytics['fastest'])} · Slowest {format_duration(analytics['slowest'])} · Spread {format_duration(analytics['spread'])} · Deviation {analytics['deviation']:.1f}s")
