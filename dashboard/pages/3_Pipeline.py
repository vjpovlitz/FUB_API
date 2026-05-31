"""Pipeline — analytics.vw_Opportunities (GHL opportunities ∪ FUB deals)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from _brand import header, money, style_fig
from _db import date_label, date_sql, q, source_sql

label = st.session_state.get("source_system", "All systems")
header("Pipeline",
       f"Opportunities & deals &mdash; {label} · created {date_label()}. "
       "GHL uses won/lost status; FUB has no lost — a deal is Won at a closed stage.")

df = q(f"""
    SELECT SourceSystem, OpportunityId, Name, Pipeline, Stage, Status,
           Value, AssignedAgent, CreatedUtc, ClosedUtc
    FROM analytics.vw_Opportunities
    WHERE 1=1 {date_sql("CreatedUtc")} {source_sql()};
""")

if df.empty:
    st.warning("No opportunities for this selection.")
    st.stop()

won = df[df["Status"] == "Won"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Opportunities", f"{len(df):,}")
c2.metric("Open", f"{int((df['Status'] == 'Open').sum()):,}")
c3.metric("Won", f"{len(won):,}")
c4.metric("Won value", money(won['Value'].sum()))

st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("By status")
    by_status = df.groupby("Status").size().reset_index(name="Count")
    fig = px.pie(by_status, names="Status", values="Count", height=340, hole=0.5)
    fig.update_traces(textinfo="percent+label")
    st.plotly_chart(style_fig(fig), width="stretch")
with col_b:
    st.subheader("By pipeline")
    by_pipe = (df.groupby("Pipeline").size().reset_index(name="Count")
               .sort_values("Count", ascending=False).head(12))
    fig2 = px.bar(by_pipe, x="Count", y="Pipeline", orientation="h", height=340)
    fig2.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(style_fig(fig2), width="stretch")

st.subheader("Count by stage")
by_stage = (df.groupby(["Stage", "Status"]).size().reset_index(name="Count")
            .sort_values("Count", ascending=False).head(40))
fig3 = px.bar(by_stage, x="Stage", y="Count", color="Status", height=400)
st.plotly_chart(style_fig(fig3), width="stretch")

st.subheader("Pipeline value by stage")
val = (df.groupby("Stage")["Value"].sum().reset_index()
       .sort_values("Value", ascending=False).head(20))
fig4 = px.bar(val, x="Stage", y="Value", height=380, labels={"Value": "Total $"})
st.plotly_chart(style_fig(fig4), width="stretch")
st.caption("Note: GoHighLevel monetary value is not tracked for this account "
           "(shows $0); dollar figures reflect Follow Up Boss deals.")

st.subheader("Wins ledger")
wins = won[["SourceSystem", "Name", "Pipeline", "Stage", "Value", "AssignedAgent", "ClosedUtc"]] \
    .sort_values("ClosedUtc", ascending=False, na_position="last")
st.dataframe(wins, width="stretch", hide_index=True)
