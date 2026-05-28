"""Agent leaderboard — fub.vw_AgentLeaderboard."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from _brand import BLUE_SCALE, header, style_fig
from _db import q

header("Agent Leaderboard", "Per-agent leads owned, events handled, and deal pipeline.")

df = q("""
    SELECT
        ISNULL(NULLIF(U.Name,''), LB.UserId) AS Agent,
        U.Role,
        LB.LeadsAssigned, LB.LeadsLast7, LB.LeadsLast30,
        LB.EventsTotal, LB.EventsLast7,
        LB.DealsTotal, LB.DealsClosed,
        LB.PipelineValueOpen, LB.PipelineValueClosed
    FROM fub.vw_AgentLeaderboard LB
    LEFT JOIN fub.Users U ON U.UserId = LB.UserId
    ORDER BY LB.LeadsAssigned DESC;
""")

if df.empty:
    st.warning("No agents in the leaderboard.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Agents", len(df))
c2.metric("Leads assigned", f"{int(df['LeadsAssigned'].sum()):,}")
c3.metric("Deals (total)", f"{int(df['DealsTotal'].sum()):,}")
c4.metric("Open pipeline $", f"{int(df['PipelineValueOpen'].sum()):,}")

st.divider()

st.subheader("Leads assigned by agent")
fig = px.bar(df, x="LeadsAssigned", y="Agent", orientation="h",
             color="DealsClosed", color_continuous_scale=BLUE_SCALE,
             labels={"LeadsAssigned": "Leads assigned", "Agent": ""}, height=380)
fig.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(style_fig(fig), width="stretch")

st.subheader("Open pipeline value by agent")
fig2 = px.bar(df, x="Agent", y=["PipelineValueOpen", "PipelineValueClosed"],
              barmode="group", height=360, labels={"value": "$", "variable": "Pipeline"})
st.plotly_chart(style_fig(fig2), width="stretch")

st.subheader("Full leaderboard")
st.dataframe(df, width="stretch", hide_index=True)
