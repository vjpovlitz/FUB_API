"""Activity — analytics.vw_Activity (calls, messages, notes, tasks, events, appts).

CRM-agnostic activity stream with time-series analysis. Respects the global
source + date filters. Calls/Notes/Tasks/Events are FUB; Messages/Appointments
are GHL — so the "Data source" selector reshapes this page too.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from _brand import header, style_fig
from _db import date_label, date_sql, q, source_sql

label = st.session_state.get("source_system", "All systems")
header("Activity", f"Calls · messages · notes · tasks &mdash; {label} · {date_label()}.")

date_c = date_sql("OccurredUtc")
src_c = source_sql()

# ---- KPIs ----
k = q(f"""
    SELECT
        COUNT_BIG(*) AS Total,
        SUM(CASE WHEN ActivityType='Call'    THEN 1 ELSE 0 END) AS Calls,
        SUM(CASE WHEN ActivityType='Message' THEN 1 ELSE 0 END) AS Messages,
        SUM(CASE WHEN ActivityType='Task'    THEN 1 ELSE 0 END) AS Tasks,
        SUM(CASE WHEN ActivityType='Note'    THEN 1 ELSE 0 END) AS Notes,
        AVG(CASE WHEN ActivityType='Call' AND DurationSec>0 THEN DurationSec END) AS AvgCallSec
    FROM analytics.vw_Activity
    WHERE 1=1 {date_c} {src_c};
""").iloc[0]

def _n(v) -> int:
    """Coerce a possibly-NULL/NaN SQL aggregate to int (GHL has no calls, etc.)."""
    return int(v) if v is not None and v == v else 0

avg_sec = _n(k["AvgCallSec"])
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Activities", f"{_n(k['Total']):,}")
c2.metric("Calls", f"{_n(k['Calls']):,}")
c3.metric("Messages", f"{_n(k['Messages']):,}")
c4.metric("Notes + Tasks", f"{_n(k['Notes']) + _n(k['Tasks']):,}")
c5.metric("Avg call", f"{avg_sec // 60}m {avg_sec % 60}s")

if _n(k["Total"]) == 0:
    st.info("No activity for this selection.")
    st.stop()

st.divider()

# ---- Daily volume by type + 7-day moving average ----
st.subheader(f"Daily activity volume — {date_label()}")
daily = q(f"""
    SELECT CAST(OccurredUtc AS DATE) AS Day, ActivityType, COUNT_BIG(*) AS N
    FROM analytics.vw_Activity
    WHERE 1=1 {date_c} {src_c}
    GROUP BY CAST(OccurredUtc AS DATE), ActivityType
    ORDER BY Day;
""")
if not daily.empty:
    daily["Day"] = daily["Day"].astype("datetime64[ns]")
    pivot = daily.pivot_table(index="Day", columns="ActivityType",
                              values="N", aggfunc="sum").fillna(0).sort_index()
    fig = px.area(pivot, height=360, labels={"value": "Activities", "Day": "", "variable": "Type"})
    # 7-day moving average of total activity, overlaid
    total = pivot.sum(axis=1)
    ma = total.rolling(7, min_periods=1).mean()
    fig.add_scatter(x=ma.index, y=ma.values, mode="lines", name="7-day avg (total)",
                    line=dict(color="#02101d", width=2.5, dash="dot"))
    st.plotly_chart(style_fig(fig), width="stretch")

# ---- Mix + per-agent ----
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Activity mix")
    mix = daily.groupby("ActivityType")["N"].sum().reset_index().sort_values("N")
    figm = px.bar(mix, x="N", y="ActivityType", orientation="h", height=320,
                  labels={"N": "Activities", "ActivityType": ""})
    st.plotly_chart(style_fig(figm), width="stretch")
with col_b:
    st.subheader("Top agents by activity")
    agents = q(f"""
        SELECT TOP 15 AgentName AS Agent, COUNT_BIG(*) AS N
        FROM analytics.vw_Activity
        WHERE AgentName IS NOT NULL AND AgentName <> '' {date_c} {src_c}
        GROUP BY AgentName
        ORDER BY N DESC;
    """)
    if not agents.empty:
        figa = px.bar(agents.sort_values("N"), x="N", y="Agent", orientation="h",
                      height=320, labels={"N": "Activities", "Agent": ""})
        st.plotly_chart(style_fig(figa), width="stretch")
    else:
        st.info("No agent-attributed activity in this window.")

# ---- Call outcomes + task status ----
col_c, col_d = st.columns(2)
with col_c:
    st.subheader("Call outcomes")
    outc = q(f"""
        SELECT Outcome, COUNT_BIG(*) AS N
        FROM analytics.vw_Activity
        WHERE ActivityType='Call' {date_c} {src_c}
        GROUP BY Outcome ORDER BY N DESC;
    """)
    if not outc.empty:
        figo = px.pie(outc, names="Outcome", values="N", hole=0.5, height=320)
        figo.update_traces(textinfo="percent+label")
        st.plotly_chart(style_fig(figo), width="stretch")
    else:
        st.info("No calls in this window.")
with col_d:
    st.subheader("Task status")
    tsk = q(f"""
        SELECT Outcome AS Status, COUNT_BIG(*) AS N
        FROM analytics.vw_Activity
        WHERE ActivityType='Task' {date_c} {src_c}
        GROUP BY Outcome ORDER BY N DESC;
    """)
    if not tsk.empty:
        figt = px.bar(tsk, x="Status", y="N", height=320, labels={"N": "Tasks"})
        st.plotly_chart(style_fig(figt), width="stretch")
    else:
        st.info("No tasks in this window.")
