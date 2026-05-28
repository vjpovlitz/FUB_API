"""Settings — placeholder (not yet wired to a backend)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from _brand import header

header("Settings", "Appearance, data refresh, and notification preferences.")

st.info("Placeholder — preferences apply to this session only.", icon=":material/info:")

# ---- Appearance ----
with st.container(border=True):
    st.subheader("Appearance")
    c1, c2 = st.columns(2)
    c1.selectbox("Theme", ["Liquid Glass (default)", "Light", "Navy"], key="set_theme")
    c2.selectbox("Accent color", ["DCR Blue", "Bright Blue", "Navy"], key="set_accent")
    st.toggle("Compact layout", key="set_compact")

# ---- Data ----
with st.container(border=True):
    st.subheader("Data")
    c1, c2 = st.columns(2)
    c1.select_slider("Cache TTL (minutes)", options=[1, 5, 10, 15, 30, 60], value=5, key="set_ttl")
    c2.selectbox("Refresh schedule", ["4×/day (current)", "Hourly", "Manual"], key="set_schedule")
    st.caption("The live refresh runs via launchd at 9:30 / 13:30 / 16:30 / 21:30.")
    if st.button("Clear query cache", key="set_clearcache"):
        st.cache_data.clear()
        st.toast("Query cache cleared.", icon=":material/check_circle:")

# ---- Notifications ----
with st.container(border=True):
    st.subheader("Notifications")
    st.toggle("Refresh-failure alerts", value=True, key="set_alert_fail")
    st.toggle("Weekly summary email", key="set_alert_weekly")
    st.text_input("Alert webhook URL", placeholder="https://hooks.slack.com/…", key="set_webhook")

# ---- About ----
with st.container(border=True):
    st.subheader("About")
    st.markdown(
        "**Dana Capital Realty · FUB Warehouse**  \n"
        "Follow Up Boss → SQL Server ETL + analytics.  \n"
        "Sister project to the GoHighLevel warehouse."
    )
