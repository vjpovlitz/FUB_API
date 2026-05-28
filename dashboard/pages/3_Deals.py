"""Deals by pipeline stage — fub.vw_DealsByStage."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.express as px
import streamlit as st

from _brand import header, style_fig
from _db import q

header("Deals by Stage",
       "FUB has no won/lost status — the pipeline stage is the lifecycle (ClosedStage = closed).")

df = q("""
    SELECT StageName, IsClosedStage, DealCount, TotalValue,
           CAST(AvgValue AS BIGINT) AS AvgValue, StageOrder
    FROM fub.vw_DealsByStage
    ORDER BY StageOrder;
""")

if df.empty:
    st.warning("No deals.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Deals", f"{int(df['DealCount'].sum()):,}")
c2.metric("Total pipeline $", f"{int(df['TotalValue'].sum()):,}")
c3.metric("Closed deals", f"{int(df.loc[df['IsClosedStage'] == True, 'DealCount'].sum()):,}")

st.divider()

st.subheader("Deal count by stage")
fig = px.bar(df, x="StageName", y="DealCount", color="IsClosedStage",
             height=380, labels={"StageName": "Stage", "DealCount": "Deals"})
st.plotly_chart(style_fig(fig), width="stretch")

st.subheader("Pipeline value by stage")
fig2 = px.bar(df, x="StageName", y="TotalValue", color="IsClosedStage",
              height=380, labels={"StageName": "Stage", "TotalValue": "Total $"})
st.plotly_chart(style_fig(fig2), width="stretch")

st.subheader("Stage detail")
st.dataframe(df, width="stretch", hide_index=True)
