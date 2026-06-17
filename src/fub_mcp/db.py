"""Read-only query execution + guardrails + markdown formatting.

The read-only `dcr_ro` login is the hard safety boundary; the validation here is
defense-in-depth so the model gets a clear error instead of a SQL permission
failure, and so obviously-destructive intent never reaches the server.

This module is schema-agnostic. Primary backend is PostgreSQL (psycopg); the
SQL Server path (pyodbc) is retained as a fallback, selected by FUB_DB_BACKEND
(see config.py). Drivers are imported lazily so the Postgres-only image (no ODBC)
never needs pyodbc, and vice-versa.
"""
from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal
from typing import Any

from .config import (
    DB_BACKEND,
    MAX_ROWS_CEILING,
    QUERY_TIMEOUT_SECONDS,
    ro_conninfo,
    ro_connection_string,
)

# Whole-word tokens that must never appear in a read query — union of SQL-standard
# writes/DDL + PostgreSQL-specific (copy/vacuum/do/call/pg_sleep/pg_read_file/…) +
# SQL-Server-specific (waitfor/dbcc/openrowset/…) verbs, so the guardrail is safe
# regardless of backend. `into` blocks SELECT ... INTO.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|exec|execute|"
    r"grant|revoke|deny|into|"
    r"copy|vacuum|analyze|reindex|cluster|refresh|do|call|"
    r"pg_sleep|pg_read_file|pg_read_binary_file|pg_terminate_backend|"
    r"pg_cancel_backend|lo_import|lo_export|set_config|dblink|"
    r"pg_ls_dir|pg_stat_file|"
    r"backup|restore|shutdown|reconfigure|openrowset|openquery|"
    r"opendatasource|waitfor|dbcc|kill)\b",
    re.IGNORECASE,
)
_PROC = re.compile(r"\b(sp|xp)_\w+", re.IGNORECASE)


def validate_select(sql: str) -> str:
    """Return a cleaned single SELECT/WITH statement or raise ValueError."""
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise ValueError("Empty query.")
    if ";" in s:
        raise ValueError("Only a single statement is allowed (no ';').")
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise ValueError("Only SELECT / WITH queries are allowed.")
    if _FORBIDDEN.search(s):
        raise ValueError(
            "Query contains a forbidden keyword. This endpoint is read-only: "
            "no writes, DDL, INTO, stored procedures, or WAITFOR."
        )
    if _PROC.search(s):
        raise ValueError("Stored-procedure calls (sp_/xp_) are not allowed.")
    return s


def run_readonly(
    sql: str, params: list[Any] | None = None, max_rows: int = 200
) -> tuple[list[str], list[list[Any]], bool]:
    """Execute a query as dcr_ro and return (columns, rows, truncated).

    Fetches at most `max_rows` (capped by MAX_ROWS_CEILING); `truncated` is True
    when more rows were available.
    """
    cap = max(1, min(max_rows, MAX_ROWS_CEILING))
    if DB_BACKEND == "sqlserver":
        import pyodbc  # lazy: only the legacy path needs the ODBC driver
        conn = pyodbc.connect(ro_connection_string(), autocommit=True)
        conn.timeout = QUERY_TIMEOUT_SECONDS
    else:
        import psycopg  # lazy: the Postgres-only image has no ODBC at all
        conn = psycopg.connect(ro_conninfo(), autocommit=True)  # timeout via statement_timeout
    try:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if cur.description is None:
            return [], [], False
        cols = [d[0] for d in cur.description]
        fetched = cur.fetchmany(cap + 1)
        truncated = len(fetched) > cap
        rows = [list(r) for r in fetched[:cap]]
        return cols, rows, truncated
    finally:
        conn.close()


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, _dt.datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, (Decimal, float)):
        f = float(v)
        if f == int(f):
            return str(int(f))
        return f"{f:.4f}".rstrip("0").rstrip(".")
    s = str(v).replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()
    return s if len(s) <= 80 else s[:77] + "..."


def to_markdown(
    cols: list[str], rows: list[list[Any]], truncated: bool, cap: int
) -> str:
    if not cols:
        return "Query ran but returned no result set."
    if not rows:
        return "No rows matched."
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join("| " + " | ".join(_fmt(c) for c in r) + " |" for r in rows)
    note = f"\n\n_{len(rows)} row(s)._"
    if truncated:
        note = (
            f"\n\n_Showing first {len(rows)} row(s); result truncated at the "
            f"{cap}-row cap. Add filters or an aggregation to narrow it._"
        )
    return f"{head}\n{sep}\n{body}{note}"


def run_select(sql: str, max_rows: int = 200) -> str:
    """Validate + run an arbitrary read query, returned as a markdown table."""
    try:
        clean = validate_select(sql)
    except ValueError as e:
        return f"Rejected: {e}"
    try:
        cols, rows, truncated = run_readonly(clean, max_rows=max_rows)
    except Exception as e:  # psycopg.Error or pyodbc.Error, depending on backend
        msg = str(e).split("]")[-1].strip()
        return f"SQL error: {msg}"
    return to_markdown(cols, rows, truncated, min(max_rows, MAX_ROWS_CEILING))
