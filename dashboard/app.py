"""FUB Warehouse Dashboard — Streamlit entry point + navigation router.

Separate app from the GHL dashboard (don't touch GHL_API prod). Reads fub.* and
analytics.* from the shared dcr_warehouse. Custom liquid-glass sidebar with a
sectioned nav (Analytics / Workspace) and placeholder account/settings/login.

Launch:
    .venv/bin/streamlit run dashboard/app.py --server.port 8502
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from _brand import apply_brand, render_filters, render_sidebar

st.set_page_config(
    page_title="Dana Capital Realty · FUB",
    page_icon="dashboard/assets/logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_brand()
st.logo("dashboard/assets/logo.png", size="large")

PAGES = {
    "Analytics": [
        st.Page("pages/0_Overview.py", title="Overview", icon=":material/dashboard:", default=True),
        st.Page("pages/1_Funnel.py", title="Lead Funnel", icon=":material/filter_alt:"),
        st.Page("pages/2_Agents.py", title="Agents", icon=":material/groups:"),
        st.Page("pages/3_Pipeline.py", title="Pipeline", icon=":material/handshake:"),
        st.Page("pages/5_Activity.py", title="Activity", icon=":material/bolt:"),
        st.Page("pages/4_CrossSystem.py", title="Cross-System", icon=":material/hub:"),
    ],
    "Workspace": [
        st.Page("pages/8_Account.py", title="Account", icon=":material/account_circle:"),
        st.Page("pages/9_Settings.py", title="Settings", icon=":material/settings:"),
    ],
}

render_filters()           # prominent global filters (source + date), above the nav
nav = st.navigation(PAGES)
render_sidebar()           # user/login card + footer, pinned below the nav
nav.run()
