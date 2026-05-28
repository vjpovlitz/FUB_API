"""Account management — placeholder (not yet wired to a backend)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from _brand import header

header("Account", "Manage your profile, workspace, and connected data sources.")

st.info("Placeholder — these controls are not yet connected to a backend.", icon=":material/info:")

user = st.session_state.get("dcr_user") or {
    "name": "Guest User", "email": "", "role": "Viewer",
}

# ---- Profile ----
with st.container(border=True):
    st.subheader("Profile")
    c1, c2 = st.columns(2)
    c1.text_input("Full name", value=user["name"])
    c2.text_input("Email", value=user.get("email", ""), placeholder="you@danacapitalrealty.com")
    c3, c4 = st.columns(2)
    c3.selectbox("Role", ["Administrator", "Manager", "Agent", "Viewer"],
                 index=["Administrator", "Manager", "Agent", "Viewer"].index(user.get("role", "Viewer"))
                 if user.get("role") in ["Administrator", "Manager", "Agent", "Viewer"] else 3)
    c4.text_input("Phone", placeholder="(555) 555-0123")
    st.button("Save profile", type="primary", disabled=True)

# ---- Workspace / plan ----
with st.container(border=True):
    st.subheader("Workspace")
    w1, w2, w3 = st.columns(3)
    w1.metric("Workspace", "Dana Capital Realty")
    w2.metric("Plan", "Internal")
    w3.metric("Seats in use", "4")

# ---- Connected sources ----
with st.container(border=True):
    st.subheader("Connected sources")
    st.markdown(
        "- **Follow Up Boss** — :green[Connected] · CRM extract\n"
        "- **GoHighLevel** — :green[Connected] · cross-system contacts\n"
        "- **SQL Server (dcr_warehouse)** — :green[Connected] · `fub.*` + `analytics.*`"
    )
    st.button("Manage connections", disabled=True)

# ---- Danger zone ----
with st.container(border=True):
    st.subheader(":red[Danger zone]")
    st.caption("Destructive actions are disabled in this placeholder build.")
    st.button("Delete workspace", disabled=True)
