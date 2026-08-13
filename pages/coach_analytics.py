"""Read-only post-race coach analytics for one finalized race session."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from split_tracker.analytics import (calculate_pace_profile, calculate_personal_records,
    calculate_team_top_n, calculate_team_spread, calculate_top5_gaps, calculate_team_pace_profile,
    compare_team_races, find_previous_comparable_race, race_metrics)
from split_tracker.branding import render_school_header
from split_tracker.formatting import format_distance, format_duration, format_pace
from split_tracker.progression import get_completed_results


def _signed_duration(value):
    if value is None: return "—"
    return f"{'+' if value > 0 else '−' if value < 0 else ''}{format_duration(abs(value))}"


def _open_results():
    st.switch_page(st.session_state.page_registry["results"])


def render():
    repo=st.session_state.repository
    session_id=st.session_state.get("analytics_session_id") or st.query_params.get("analytics_session")
    race_id=st.session_state.get("analytics_race_id") or st.query_params.get("analytics_race")
    session=repo.get_race_session(session_id) if repo and session_id else None
    race=repo.get_race(race_id) if repo and race_id else None
    if not session or not race or session.race_id != race.id:
        st.warning("Choose Coach Analytics from a completed race."); return
    if session.status != "completed":
        st.warning("Analytics become authoritative after Finalize & Publish Results.")
        if st.button("Return to Results",use_container_width=True): _open_results()
        return
    if race.name.lstrip().upper().startswith("TEST"):
        st.info("Test races are excluded from authoritative Coach Analytics.")
        return
    meet=repo.get_meet(race.meet_id); history=get_completed_results(repo)
    current=[result for result in history if result.session_id==session.id]
    if not current: st.info("No finalized results are available for this session."); return
    render_school_header(st.session_state.school_profile,"Post-Race Analytics",subtitle=f"{meet.name} • {race.name}")
    st.caption(f"{format_distance(race.distance_meters)} • {meet.meet_date or 'Date unavailable'} • ✅ FINAL")
    metrics=race_metrics(current,history); records=calculate_personal_records(current,history)
    finishers=calculate_team_top_n(current,len(current)); profiles={r.athlete_id:calculate_pace_profile(r) for r in current}
    cards=st.columns(6)
    for col,(label,value) in zip(cards,[('Finishers',str(metrics['finishers'])),('PRs',str(metrics['prs'])),('1–5 Spread',format_duration(metrics['spread_5']) if metrics['spread_5'] is not None else 'N/A'),('1–7 Spread',format_duration(metrics['spread_7']) if metrics['spread_7'] is not None else 'N/A'),('Average Finish',format_duration(metrics['average_finish'])),('Early → Late',_signed_duration(metrics['pace_change']))]): col.metric(label,value)
    st.subheader("Performance Highlights")
    biggest_pr=max((record for record in records if record.is_pr),key=lambda record:record.improvement,default=None)
    negative=min((r for r in finishers if profiles[r.athlete_id] and profiles[r.athlete_id].change < 0),key=lambda r:profiles[r.athlete_id].change,default=None)
    fade=max((r for r in finishers if profiles[r.athlete_id] and profiles[r.athlete_id].change > 0),key=lambda r:profiles[r.athlete_id].change,default=None)
    highlights=st.columns(4)
    highlights[0].write(f"**Biggest PR**\n\n{biggest_pr.result.athlete_name} by {format_duration(biggest_pr.improvement)}" if biggest_pr else "**Biggest PR**\n\nNone")
    highlights[1].write(f"**Biggest Negative Split**\n\n{negative.athlete_name}: {_signed_duration(profiles[negative.athlete_id].change)}/mi" if negative else "**Biggest Negative Split**\n\nNot enough split data")
    highlights[2].write(f"**Largest Late Fade**\n\n{fade.athlete_name}: {_signed_duration(profiles[fade.athlete_id].change)}/mi" if fade else "**Largest Late Fade**\n\nNot enough split data")
    highlights[3].write(f"**First Finisher**\n\n{finishers[0].athlete_name} — {format_duration(finishers[0].finish_seconds)}" if finishers else "**First Finisher**\n\n—")
    pace=calculate_team_pace_profile(finishers)
    st.caption(f"Average early pace {format_pace(pace['early'])} • average late pace {format_pace(pace['late'])} • change {_signed_duration(pace['change'])}/mi • valid athletes {pace['valid']} of {pace['total']}")
    st.subheader("Varsity Top 7")
    st.caption("Eligibility is the selected race roster; Swing athletes retain their classification while ranking in the race they ran.")
    st.dataframe([{"Place":r.place or "—","Athlete":r.athlete_name,"Finish":format_duration(r.finish_seconds),"Team Rank":i} for i,r in enumerate(calculate_team_top_n(current),1)],hide_index=True,use_container_width=True)
    st.subheader("Top-5 Compression")
    gaps=calculate_top5_gaps(current)
    st.write(" • ".join(f"#{i} → #{i+1}: {format_duration(gap)}" for i,gap in enumerate(gaps,1)) or "Fewer than two finishers")
    st.subheader("Previous Race Comparison")
    previous=find_previous_comparable_race(current[0],history)
    if not previous: st.info("No prior comparable finalized race.")
    else:
        st.caption(f"Compared with: {previous[0].meet_name} — {previous[0].race_date or 'date unavailable'}")
        labels={"average_finish":"Avg Finish","spread_5":"1–5 Spread","spread_7":"1–7 Spread","early":"Avg Early Pace","late":"Avg Late Pace","prs":"PRs","finishers":"Finishers"}
        rows=[]
        for item in compare_team_races(previous,current,history):
            count=item['metric'] in {'prs','finishers'}; formatter=(lambda x:str(int(x)) if x is not None else '—') if count else format_duration
            rows.append({"Metric":labels[item['metric']],"Previous":formatter(item['previous']),"Current":formatter(item['current']),"Change":_signed_duration(item['change']) if not count else (_signed_duration(item['change']) if item['change'] is not None else '—')})
        st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    st.subheader("Athlete Analysis")
    record_by_id={record.result.athlete_id:record for record in records}; previous_by_id={r.athlete_id:r for r in (previous or [])}
    table=[]
    for rank,result in enumerate(finishers,1):
        record=record_by_id[result.athlete_id]; profile=profiles[result.athlete_id]; prior=previous_by_id.get(result.athlete_id)
        table.append({"Team Rank":rank,"Athlete":result.athlete_name,"Classification":result.classification or "—","Finish":format_duration(result.finish_seconds),"Average Pace":format_pace(result.pace_seconds_per_mile),"Previous Best":format_duration(record.previous_best),"PR":"Yes" if record.is_pr else (f"First recorded {format_distance(result.distance_meters)}" if record.is_first else "No"),"PR Improvement":format_duration(record.improvement),"Early Pace":format_pace(profile.early_pace) if profile else "—","Late Pace":format_pace(profile.late_pace) if profile else "—","Pace Change":_signed_duration(profile.change) if profile else "—","Previous Race":format_duration(prior.finish_seconds) if prior else "—","Change vs Previous":_signed_duration(result.finish_seconds-prior.finish_seconds) if prior and prior.finish_seconds else "—","Status":result.status})
    for result in current:
        if result not in finishers: table.append({"Team Rank":"—","Athlete":result.athlete_name,"Classification":result.classification or "—","Finish":"—","Average Pace":"—","Previous Best":"—","PR":"No","PR Improvement":"—","Early Pace":"—","Late Pace":"—","Pace Change":"—","Previous Race":"—","Change vs Previous":"—","Status":result.status})
    st.dataframe(pd.DataFrame(table),hide_index=True,use_container_width=True)
