"""Coach team progression dashboard."""
import pandas as pd
import streamlit as st
from split_tracker.auth import AuthenticationError, require_admin
from split_tracker.branding import render_school_header
from split_tracker.formatting import format_distance, format_duration
from split_tracker.progression import get_completed_results, team_progress

def render():
    try: require_admin(st.session_state.get("app_identity"))
    except AuthenticationError as exc: st.error(str(exc)); return
    repo=st.session_state.repository; render_school_header(st.session_state.school_profile,"Team Progress")
    athletes=repo.list_athletes(include_archived=True); results=get_completed_results(repo)
    seasons=sorted({r.season for r in results if r.season},reverse=True); distances=sorted({r.distance_meters for r in results})
    c1,c2,c3,c4=st.columns(4); season=c1.selectbox("Season",seasons or [None]); distance=c2.selectbox("Distance",distances or [None],format_func=lambda x:format_distance(x) if x else "All")
    groups=sorted({a.team_division for a in athletes if a.team_division}); group=c3.selectbox("Group",["All",*groups]); gender=c4.selectbox("Gender",["All",*sorted({a.gender for a in athletes if a.gender})])
    selected=[a for a in athletes if (group=="All" or a.team_division==group) and (gender=="All" or a.gender==gender)]
    rows=team_progress(results,selected,season=season,distance_meters=distance)
    sort=st.selectbox("Sort",["Biggest improvement","Fastest season best","Latest result","Athlete name"])
    keys={"Biggest improvement":lambda r:-(r["improvement"] or -1),"Fastest season best":lambda r:r["season_best"] or float("inf"),"Latest result":lambda r:r["latest"].race_date or 0,"Athlete name":lambda r:r["athlete"].display_name.casefold()}; rows.sort(key=keys[sort],reverse=sort=="Latest result")
    st.dataframe(pd.DataFrame([{"Athlete":r["athlete"].display_name,"Group":r["athlete"].team_division or "—","Season Best":format_duration(r["season_best"]),"Previous Race":format_duration(r["previous"].finish_seconds) if r["previous"] else "—","Improvement":format_duration(r["improvement"]),"Last Race":r["latest"].race_date} for r in rows]),hide_index=True,use_container_width=True)
