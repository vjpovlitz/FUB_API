"""Overview — CRM-agnostic KPI tiles and trends (analytics.* only)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from _brand import header, money, style_fig
from _db import date_label, date_sql, q, source_sql

label = st.session_state.get("source_system", "All systems")
header("Warehouse Overview",
       f"Live KPIs across every connected CRM &mdash; {label} · {date_label()}.")

src_c = source_sql()                       # narrows to the selected SourceSystem
date_c = date_sql("DateAddedUtc")          # narrows to the selected date window

# ---- Top tiles (all from vendor-neutral analytics views) ----
totals = q(f"""
    SELECT
        (SELECT COUNT_BIG(*) FROM analytics.vw_AllContacts   WHERE 1=1 {src_c}) AS Contacts,
        (SELECT COUNT_BIG(*) FROM analytics.vw_AllContacts
            WHERE DateAddedUtc >= DATEADD(DAY, -7, GETUTCDATE()) {src_c})        AS NewLeads7d,
        (SELECT COUNT_BIG(*) FROM analytics.vw_Opportunities  WHERE 1=1 {src_c}) AS Opps,
        (SELECT COUNT_BIG(*) FROM analytics.vw_Opportunities
            WHERE Status = 'Won' {src_c})                                       AS Won,
        (SELECT ISNULL(SUM(Value),0) FROM analytics.vw_Opportunities
            WHERE Status = 'Won' {src_c})                                       AS WonValue
""").iloc[0]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Contacts", f"{int(totals['Contacts']):,}")
c2.metric("New leads (7d)", f"{int(totals['NewLeads7d']):,}")
c3.metric("Opportunities", f"{int(totals['Opps']):,}")
c4.metric("Won", f"{int(totals['Won']):,}")
c5.metric("Won value", money(totals['WonValue']))

st.divider()

# ---- Daily new leads (windowed), split by system ----
st.subheader(f"Daily new leads — {date_label()}")
trend = q(f"""
    SELECT CAST(DateAddedUtc AS DATE) AS LeadDate, SourceSystem, COUNT_BIG(*) AS NewLeads
    FROM analytics.vw_AllContacts
    WHERE 1=1 {date_c} {src_c}
    GROUP BY CAST(DateAddedUtc AS DATE), SourceSystem
    ORDER BY LeadDate;
""")
if not trend.empty:
    pivot = trend.pivot_table(index="LeadDate", columns="SourceSystem",
                              values="NewLeads", aggfunc="sum").fillna(0)
    st.bar_chart(pivot, height=260)
else:
    st.info(f"No leads created in the {date_label()} for this selection.")

# ---- Source mix + cross-system ----
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Top lead sources")
    srcs = q(f"""
        SELECT TOP 10 ISNULL(NULLIF(Source,''),'(unknown)') AS Source, COUNT_BIG(*) AS People
        FROM analytics.vw_AllContacts
        WHERE 1=1 {date_c} {src_c}
        GROUP BY ISNULL(NULLIF(Source,''),'(unknown)')
        ORDER BY People DESC;
    """)
    if not srcs.empty:
        fig_s = px.bar(srcs.sort_values("People"), x="People", y="Source",
                       orientation="h", height=300)
        st.plotly_chart(style_fig(fig_s), width="stretch")
    else:
        st.info("No sources in this window.")

with col_b:
    st.subheader("Contacts by system")
    xs = q("SELECT SourceSystem, COUNT_BIG(*) AS Contacts FROM analytics.vw_AllContacts GROUP BY SourceSystem;")
    fig_x = px.bar(xs.sort_values("Contacts"), x="Contacts", y="SourceSystem",
                   orientation="h", height=300)
    st.plotly_chart(style_fig(fig_x), width="stretch")
    st.caption(f"Total unified contacts (all systems): {int(xs['Contacts'].sum()):,}")

st.divider()
st.caption("Use the sidebar **Data source** selector to scope every page to one CRM, "
           "then drill into Funnel · Agents · Pipeline · Cross-System.")
