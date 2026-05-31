"""Agent leaderboard — analytics.vw_AgentLeaderboard (CRM-agnostic, source-filtered)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from _brand import BLUE_SCALE, header, money, style_fig
from _db import q, source_sql

label = st.session_state.get("source_system", "All systems")
header("Agent Leaderboard",
       f"Per-agent leads, activity, and deal pipeline &mdash; showing: {label}.")

df = q(f"""
    SELECT SourceSystem, AgentName AS Agent, Role,
           LeadsAssigned, LeadsLast7, LeadsLast30,
           ActivityCount, DealsTotal, DealsWon,
           PipelineValueOpen, PipelineValueWon
    FROM analytics.vw_AgentLeaderboard
    WHERE 1=1 {source_sql()}
    ORDER BY LeadsAssigned DESC;
""")

if df.empty:
    st.warning("No agents for this selection.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Agents", len(df))
c2.metric("Leads assigned", f"{int(df['LeadsAssigned'].sum()):,}")
c3.metric("Deals won", f"{int(df['DealsWon'].sum()):,}")
c4.metric("Open pipeline $", money(df['PipelineValueOpen'].sum()))

st.divider()

st.subheader("Leads assigned by agent")
top = df.head(25)
fig = px.bar(top, x="LeadsAssigned", y="Agent", orientation="h",
             color="DealsWon", color_continuous_scale=BLUE_SCALE,
             labels={"LeadsAssigned": "Leads assigned", "Agent": ""}, height=460)
fig.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(style_fig(fig), width="stretch")

st.subheader("Pipeline value by agent")
fig2 = px.bar(df.head(25), x="Agent", y=["PipelineValueOpen", "PipelineValueWon"],
              barmode="group", height=360, labels={"value": "$", "variable": "Pipeline"})
st.plotly_chart(style_fig(fig2), width="stretch")

st.subheader("Full leaderboard")
st.dataframe(df, width="stretch", hide_index=True)
