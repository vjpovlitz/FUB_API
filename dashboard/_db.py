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
