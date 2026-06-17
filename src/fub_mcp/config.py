"""Connection config for the read-only MCP login.

Primary backend is **PostgreSQL** (shared dcr_warehouse on the VPS), read as the
`dcr_ro` role via PG_RO_* — the same env names as GHL_API / postgres/_pg.py. The
legacy **SQL Server** path (pyodbc, MCP_SQL_* / GHL_SQL_*) is retained as a
fallback and selected with `FUB_DB_BACKEND=sqlserver`, so we can revert/debug if
needed. Either way the read-only role is the hard safety boundary.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

# "postgres" (default) | "sqlserver" (legacy fallback).
DB_BACKEND = os.getenv("FUB_DB_BACKEND", "postgres").strip().lower()

# Query timeout (seconds) applied to every read. Bounds runaway scans.
QUERY_TIMEOUT_SECONDS = int(os.getenv("MCP_QUERY_TIMEOUT", "30"))
# Hard ceiling on rows returned to the model, regardless of a tool's request.
MAX_ROWS_CEILING = int(os.getenv("MCP_MAX_ROWS", "500"))


def ro_conninfo() -> str:
    """libpq conninfo for the read-only `dcr_ro` role (PostgreSQL, primary).

    statement_timeout bounds runaway scans (replaces pyodbc's conn.timeout) and
    default_transaction_read_only re-asserts read-only at the session level —
    defense in depth behind the dcr_ro grants and validate_select().
    """
    override = os.getenv("PG_RO_URL")
    opts = (f"-c statement_timeout={QUERY_TIMEOUT_SECONDS * 1000} "
            f"-c default_transaction_read_only=on")
    if override:
        sep = "&" if "?" in override else "?"
        return f"{override}{sep}options={opts.replace(' ', '%20')}"
    host = os.environ["PG_HOST"]
    port = os.getenv("PG_PORT", "5432")
    db = os.getenv("PG_DATABASE", "dcr_warehouse")
    user = os.getenv("PG_RO_USER", "dcr_ro")
    pw = os.environ["PG_RO_PASSWORD"]
    ssl = os.getenv("PGSSLMODE", "require")
    return (f"host={host} port={port} dbname={db} user={user} password={pw} "
            f"sslmode={ssl} options='{opts}'")


def ro_connection_string() -> str:
    """ODBC connection string for the read-only login (SQL Server, legacy fallback)."""
    server = os.environ["GHL_SQL_SERVER"]
    database = os.getenv("GHL_SQL_DATABASE", "dcr_warehouse")
    user = os.environ["MCP_SQL_USER"]
    password = os.environ["MCP_SQL_PASSWORD"]
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};UID={user};PWD={password};DATABASE={database};"
        "TrustServerCertificate=yes;Encrypt=no;"
    )
