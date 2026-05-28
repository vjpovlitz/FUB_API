"""Lead funnel — fub.vw_DailyLeadFunnel."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from _brand import header, style_fig
from _db import q

header("Lead Funnel",
       "Leads → engaged (≥1 event) → deal created → deal closed, by created-date &amp; source.")

df = q("""
    SELECT LeadDate, LeadSource, LeadsCreated, EngagedContacts, DealsCreated, DealsClosed,
           CAST(EngagedPct AS DECIMAL(5,1)) AS EngagedPct,
           CAST(DealPct    AS DECIMAL(5,1)) AS DealPct,
           CAST(ClosedPct  AS DECIMAL(5,1)) AS ClosedPct
    FROM fub.vw_DailyLeadFunnel
    ORDER BY LeadDate DESC;
""")

if df.empty:
    st.warning("No funnel rows.")
    st.stop()

# ---- Funnel totals ----
tot = df[["LeadsCreated", "EngagedContacts", "DealsCreated", "DealsClosed"]].sum()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Leads created", f"{int(tot['LeadsCreated']):,}")
c2.metric("Engaged", f"{int(tot['EngagedContacts']):,}")
c3.metric("Deals created", f"{int(tot['DealsCreated']):,}")
c4.metric("Deals closed", f"{int(tot['DealsClosed']):,}")

st.divider()

# ---- Funnel bar ----
st.subheader("Overall funnel")
funnel = px.funnel(
    x=[int(tot["LeadsCreated"]), int(tot["EngagedContacts"]),
       int(tot["DealsCreated"]), int(tot["DealsClosed"])],
    y=["Leads", "Engaged", "Deals", "Closed"],
    height=320,
)
st.plotly_chart(style_fig(funnel), width="stretch")

# ---- By source ----
st.subheader("Funnel by source")
by_src = (df.groupby("LeadSource")[["LeadsCreated", "EngagedContacts", "DealsCreated", "DealsClosed"]]
          .sum().reset_index().sort_values("LeadsCreated", ascending=False).head(12))
fig = px.bar(by_src, x="LeadSource", y=["LeadsCreated", "EngagedContacts", "DealsCreated", "DealsClosed"],
             barmode="group", height=420, labels={"value": "Count", "variable": "Stage"})
st.plotly_chart(style_fig(fig), width="stretch")

# ---- Detail table ----
st.subheader("Daily detail")
st.dataframe(df, width="stretch", hide_index=True)
