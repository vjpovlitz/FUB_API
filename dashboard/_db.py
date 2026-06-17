"""Shared DB connection + cached query helper for the FUB Streamlit dashboard.

Primary backend is **PostgreSQL** (shared dcr_warehouse on the VPS, read via the
PG_* env as the read-only `dcr_ro` role), querying the `fub.*` tables/views and the
cross-system `analytics.*` views. The legacy **SQL Server** path (pyodbc, GHL_SQL_*)
is retained as a fallback, selected with `FUB_DB_BACKEND=sqlserver`. Drivers import
lazily so the Postgres-only image needs no ODBC.

NOTE: some dashboard *page* queries still use SQL-Server dialect (DATEADD, ISNULL,
GETUTCDATE, TOP) — those must be rewritten for Postgres and verified on the VPS.
See MIGRATION_NOTES.md. `date_sql` below is already dialect-aware.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# "postgres" (default) | "sqlserver" (legacy fallback).
DB_BACKEND = os.getenv("FUB_DB_BACKEND", "postgres").strip().lower()


def _sqlserver_conn_str() -> str:
    server = os.getenv("GHL_SQL_SERVER", "localhost,1433")
    user = os.getenv("GHL_SQL_USER", "sa")
    pw = os.getenv("GHL_SQL_PASSWORD", "")
    db = os.getenv("GHL_SQL_DATABASE", "dcr_warehouse")
    return (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server};"
        f"UID={user};PWD={pw};DATABASE={db};"
        f"TrustServerCertificate=yes;Encrypt=no;"
    )


def _pg_conninfo() -> str:
    host = os.environ["PG_HOST"]
    port = os.getenv("PG_PORT", "5432")
    db = os.getenv("PG_DATABASE", "dcr_warehouse")
    user = os.getenv("PG_RO_USER", "dcr_ro")
    pw = os.environ["PG_RO_PASSWORD"]
    ssl = os.getenv("PGSSLMODE", "require")
    return f"host={host} port={port} dbname={db} user={user} password={pw} sslmode={ssl}"


@st.cache_resource
def get_connection():
    if DB_BACKEND == "sqlserver":
        import pyodbc
        return pyodbc.connect(_sqlserver_conn_str(), autocommit=True)
    import psycopg
    return psycopg.connect(_pg_conninfo(), autocommit=True)


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
        if DB_BACKEND == "sqlserver":
            return (f" {leading} {col} >= '{s.isoformat()}'"
                    f" AND {col} < DATEADD(DAY, 1, '{e.isoformat()}')")
        return (f" {leading} {col} >= '{s.isoformat()}'"
                f" AND {col} < (DATE '{e.isoformat()}' + INTERVAL '1 day')")
    days = selected_days()
    if not days:
        return ""
    if DB_BACKEND == "sqlserver":
        return f" {leading} {col} >= DATEADD(DAY, -{int(days)}, GETUTCDATE())"
    return f" {leading} {col} >= (now() AT TIME ZONE 'utc') - INTERVAL '{int(days)} days'"
