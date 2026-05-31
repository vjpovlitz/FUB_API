"""Shared DB connection + cached query helper for the FUB Streamlit dashboard.

Reads the same SQL Server warehouse as GHL_API (dcr_warehouse), querying the
`fub.*` tables/views and the cross-system `analytics.*` views. Connection vars
are the shared GHL_SQL_* names (see .env). Self-signed cert on the server, so
the connect string must keep TrustServerCertificate=yes;Encrypt=no;.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pyodbc
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


def _conn_str() -> str:
    server = os.getenv("GHL_SQL_SERVER", "localhost,1433")
    user = os.getenv("GHL_SQL_USER", "sa")
    pw = os.getenv("GHL_SQL_PASSWORD", "")
    db = os.getenv("GHL_SQL_DATABASE", "dcr_warehouse")
    return (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server};"
        f"UID={user};PWD={pw};DATABASE={db};"
        f"TrustServerCertificate=yes;Encrypt=no;"
    )


@st.cache_resource
def get_connection() -> "pyodbc.Connection":
    return pyodbc.connect(_conn_str(), autocommit=True)


@st.cache_data(ttl=300)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a query, return a DataFrame. Cached 5 min (hit Rerun after SQL edits)."""
    return pd.read_sql(sql, get_connection(), params=params)


# --- CRM-agnostic source filter ----------------------------------------------
# The dashboard reads only vendor-neutral analytics.* views; this global filter
# narrows any of them to one CRM (or all). Values are whitelisted, so the SQL
# fragment is safe to inline. See project memory: dashboard-productization.
SOURCE_LABELS: dict[str, str | None] = {
    "All systems": None,
    "Follow Up Boss": "FollowUpBoss",
    "GoHighLevel": "GoHighLevel",
}


def selected_source() -> str | None:
    """The SourceSystem value for the active sidebar selection (None = all)."""
    label = st.session_state.get("source_system", "All systems")
    return SOURCE_LABELS.get(label)


def source_sql(col: str = "SourceSystem", leading: str = "AND") -> str:
    """SQL fragment narrowing `col` to the selected CRM, or '' for all systems.

    Value comes from a fixed whitelist (SOURCE_LABELS) so inlining is injection-safe.
    Pair with a `WHERE 1=1` so the leading 'AND' always composes cleanly.
    """
    val = selected_source()
    return f" {leading} {col} = '{val}'" if val else ""


# --- Global date-range filter (drives time-series analysis) -------------------
# Maps the sidebar slider label to a look-back window in days (None = all time).
DATE_PRESETS: dict[str, int | None] = {
    "7d": 7, "30d": 30, "90d": 90, "1y": 365, "All": None,
}


def selected_days() -> int | None:
    """Look-back window in days for the active date-range slider (None = all)."""
    return DATE_PRESETS.get(st.session_state.get("date_range", "90d"))


def custom_range() -> tuple | None:
    """The (start, end) date objects if Custom mode is on with a full range, else None."""
    if not st.session_state.get("date_custom"):
        return None
    rng = st.session_state.get("date_custom_range")
    if isinstance(rng, (list, tuple)) and len(rng) == 2 and all(rng):
        return rng[0], rng[1]
    return None


def date_label() -> str:
    """Human label for the active window, e.g. 'last 90 days' / 'Mar 01 – May 28, 2026'."""
    cr = custom_range()
    if cr:
        s, e = cr
        return f"{s:%b %d} – {e:%b %d, %Y}"
    label = st.session_state.get("date_range", "90d")
    return {
        "7d": "last 7 days", "30d": "last 30 days", "90d": "last 90 days",
        "1y": "last 12 months", "All": "all time",
    }.get(label, "last 90 days")


def date_sql(col: str, leading: str = "AND") -> str:
    """SQL fragment limiting `col` to the active window, or '' for all time.

    Custom mode -> BETWEEN start and end (end-inclusive). Otherwise a whitelisted
    integer look-back. Date values come from date pickers (date objects formatted
    ISO), so inlining is injection-safe.
    """
    cr = custom_range()
    if cr:
        s, e = cr
        return (f" {leading} {col} >= '{s.isoformat()}'"
                f" AND {col} < DATEADD(DAY, 1, '{e.isoformat()}')")
    days = selected_days()
    return f" {leading} {col} >= DATEADD(DAY, -{int(days)}, GETUTCDATE())" if days else ""
