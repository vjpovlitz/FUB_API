"""Shared PostgreSQL connection helper for the migration scripts.

One place builds the conninfo so the loader, verifier, and (later) the MCP /
dashboard ports all agree. Mirrors fub_mcp/config.py's read-only split: `dcr`
for read/write, `dcr_ro` for read-only.

Env (.env, loaded here):
    PG_HOST          Tailnet IP / host of the VPS
    PG_PORT          default 5432
    PG_DATABASE      default dcr_warehouse
    PG_USER          read/write role        (default dcr)
    PG_PASSWORD
    PG_RO_USER       read-only role         (default dcr_ro)
    PG_RO_PASSWORD
    PGSSLMODE        default require
    PG_URL / PG_RO_URL   optional full-URL overrides (win if set)
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass


def pg_url(readonly: bool = False) -> str:
    override = os.getenv("PG_RO_URL" if readonly else "PG_URL")
    if override:
        return override
    host = os.environ["PG_HOST"]
    port = os.getenv("PG_PORT", "5432")
    db = os.getenv("PG_DATABASE", "dcr_warehouse")
    user = os.getenv("PG_RO_USER", "dcr_ro") if readonly else os.getenv("PG_USER", "dcr")
    pw = os.environ["PG_RO_PASSWORD" if readonly else "PG_PASSWORD"]
    ssl = os.getenv("PGSSLMODE", "require")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}?sslmode={ssl}"


def connect(readonly: bool = False):
    """Open an autocommit psycopg connection (imported lazily)."""
    import psycopg
    return psycopg.connect(pg_url(readonly), autocommit=True)


def apply_sql_file(conn, path: Path) -> None:
    """Execute a generated .sql file (DDL / views).

    Splits on ';' — safe for our generated DDL and the rewritten views, which
    contain no procedural bodies, dollar-quoting, or string literals with ';'.
    For anything fancier, apply with `psql -f` instead.
    """
    raw = path.read_text(encoding="utf-8")
    # Drop full-line comments first, THEN split — otherwise a statement chunk
    # that begins with a comment line would be skipped whole.
    code = "\n".join(ln for ln in raw.splitlines() if not ln.lstrip().startswith("--"))
    statements = [s.strip() for s in code.split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
