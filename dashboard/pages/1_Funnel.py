"""Lead funnel — analytics.vw_LeadFunnel (CRM-agnostic, source-filtered)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from _brand import header, style_fig
from _db import date_label, date_sql, q, source_sql

label = st.session_state.get("source_system", "All systems")
header("Lead Funnel",
       f"Leads → engaged (≥1 activity) → opportunity → won &mdash; {label} · {date_label()}.")

df = q(f"""
    SELECT LeadDate, LeadSource, SourceSystem,
           LeadsCreated, EngagedContacts, OppsCreated, OppsWon
    FROM analytics.vw_LeadFunnel
    WHERE 1=1 {date_sql("LeadDate")} {source_sql()}
    ORDER BY LeadDate DESC;
""")

if df.empty:
    st.warning("No funnel rows for this selection.")
    st.stop()

# ---- Funnel totals ----
tot = df[["LeadsCreated", "EngagedContacts", "OppsCreated", "OppsWon"]].sum()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Leads created", f"{int(tot['LeadsCreated']):,}")
c2.metric("Engaged", f"{int(tot['EngagedContacts']):,}")
c3.metric("Opportunities", f"{int(tot['OppsCreated']):,}")
c4.metric("Won", f"{int(tot['OppsWon']):,}")

st.divider()

# ---- Funnel bar ----
st.subheader("Overall funnel")
funnel = px.funnel(
    x=[int(tot["LeadsCreated"]), int(tot["EngagedContacts"]),
       int(tot["OppsCreated"]), int(tot["OppsWon"])],
    y=["Leads", "Engaged", "Opportunities", "Won"],
    height=320,
)
st.plotly_chart(style_fig(funnel), width="stretch")

# ---- By source ----
st.subheader("Funnel by source")
by_src = (df.groupby("LeadSource")[["LeadsCreated", "EngagedContacts", "OppsCreated", "OppsWon"]]
          .sum().reset_index().sort_values("LeadsCreated", ascending=False).head(12))
fig = px.bar(by_src, x="LeadSource", y=["LeadsCreated", "EngagedContacts", "OppsCreated", "OppsWon"],
             barmode="group", height=420, labels={"value": "Count", "variable": "Stage"})
st.plotly_chart(style_fig(fig), width="stretch")

# ---- Detail table ----
st.subheader("Daily detail")
st.dataframe(df, width="stretch", hide_index=True)
