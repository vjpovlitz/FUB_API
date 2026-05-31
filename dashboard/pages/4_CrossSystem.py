"""Cross-system contacts — analytics.vw_AllContacts (GHL + FUB unioned)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from _brand import BLUE, NAVY, header, style_fig
from _db import date_sql, q

header("Cross-System Contacts",
       "analytics.vw_AllContacts — GoHighLevel + Follow Up Boss in one normalized view.")

by_sys = q("""
    SELECT SourceSystem, COUNT_BIG(*) AS Contacts,
           SUM(CASE WHEN Email <> '' THEN 1 ELSE 0 END) AS WithEmail,
           SUM(CASE WHEN Phone <> '' THEN 1 ELSE 0 END) AS WithPhone
    FROM analytics.vw_AllContacts
    GROUP BY SourceSystem ORDER BY Contacts DESC;
""")

if by_sys.empty:
    st.warning("analytics.vw_AllContacts returned no rows.")
    st.stop()

c1, c2 = st.columns(2)
c1.metric("Total unified contacts", f"{int(by_sys['Contacts'].sum()):,}")
c2.metric("Source systems", len(by_sys))

st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Contacts by source system")
    fig = px.pie(by_sys, names="SourceSystem", values="Contacts", height=340, hole=0.5,
                 color_discrete_sequence=[BLUE, NAVY])
    fig.update_traces(textinfo="percent+label")
    st.plotly_chart(style_fig(fig), width="stretch")
with col_b:
    st.subheader("Contactability")
    st.dataframe(by_sys, width="stretch", hide_index=True)

st.subheader("New contacts per month (both systems)")
# Cross-system view always compares both CRMs; only the date window is applied.
_window = date_sql("DateAddedUtc", leading="AND") or \
    " AND DateAddedUtc >= DATEADD(MONTH, -12, GETUTCDATE())"
monthly = q(f"""
    SELECT DATEFROMPARTS(YEAR(DateAddedUtc), MONTH(DateAddedUtc), 1) AS Month,
           SourceSystem, COUNT_BIG(*) AS Contacts
    FROM analytics.vw_AllContacts
    WHERE 1=1 {_window}
    GROUP BY DATEFROMPARTS(YEAR(DateAddedUtc), MONTH(DateAddedUtc), 1), SourceSystem
    ORDER BY Month;
""")
if not monthly.empty:
    fig2 = px.bar(monthly, x="Month", y="Contacts", color="SourceSystem",
                  barmode="group", height=380,
                  color_discrete_sequence=[BLUE, NAVY])
    st.plotly_chart(style_fig(fig2), width="stretch")
else:
    st.info("No contacts added in the last 12 months.")
