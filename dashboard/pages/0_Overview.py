"""Overview — top-level KPI tiles and trends."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from _brand import header
from _db import q

header("Follow Up Boss Warehouse",
       "Live KPIs across people, events &amp; deals — and the cross-system contact view.")

# ---- Top tiles ----
totals = q("""
    SELECT
        (SELECT COUNT_BIG(*) FROM fub.People)  AS People,
        (SELECT COUNT_BIG(*) FROM fub.Events)  AS Events,
        (SELECT COUNT_BIG(*) FROM fub.Deals)   AS Deals,
        (SELECT COUNT_BIG(*) FROM fub.Deals d
            JOIN fub.Stages s ON s.StageId = d.StageId AND s.StageKind = 'Deal'
            WHERE s.ClosedStage = 1)           AS DealsClosed,
        (SELECT COUNT_BIG(*) FROM fub.People
            WHERE CreatedUtc >= DATEADD(DAY, -7, GETUTCDATE())) AS NewLeads7d,
        (SELECT COUNT_BIG(*) FROM fub.People WHERE Stage <> 'Trash') AS ActivePeople
""").iloc[0]

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("People", f"{totals['People']:,}")
c2.metric("Active (non-Trash)", f"{int(totals['ActivePeople']):,}")
c3.metric("Events", f"{totals['Events']:,}")
c4.metric("Deals", f"{totals['Deals']:,}")
c5.metric("Deals closed", f"{int(totals['DealsClosed']):,}")
c6.metric("New leads (7d)", f"{int(totals['NewLeads7d']):,}")

st.divider()

# ---- Daily new leads ----
st.subheader("Daily new leads — last 90 days")
trend = q("""
    SELECT CAST(CreatedUtc AS DATE) AS LeadDate, COUNT_BIG(*) AS NewLeads
    FROM fub.People
    WHERE CreatedUtc >= DATEADD(DAY, -90, GETUTCDATE())
    GROUP BY CAST(CreatedUtc AS DATE)
    ORDER BY LeadDate;
""")
if not trend.empty:
    st.bar_chart(trend.set_index("LeadDate")["NewLeads"], height=260, color="#005dcf")
else:
    st.info("No leads created in the last 90 days.")

# ---- Source + cross-system ----
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Top lead sources")
    src = q("""
        SELECT TOP 10 ISNULL(NULLIF(Source,''),'(unknown)') AS Source, COUNT_BIG(*) AS People
        FROM fub.People GROUP BY ISNULL(NULLIF(Source,''),'(unknown)')
        ORDER BY People DESC;
    """)
    st.bar_chart(src.set_index("Source")["People"], height=300, color="#005dcf")

with col_b:
    st.subheader("Cross-system contacts")
    xs = q("SELECT SourceSystem, COUNT_BIG(*) AS Contacts FROM analytics.vw_AllContacts GROUP BY SourceSystem;")
    st.bar_chart(xs.set_index("SourceSystem")["Contacts"], height=300, color="#005dcf")
    st.caption(f"Total unified contacts: {int(xs['Contacts'].sum()):,}")

st.divider()
st.caption("Use the sidebar to drill into Funnel · Agents · Deals · Cross-System.")
