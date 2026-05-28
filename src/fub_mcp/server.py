"""FastMCP server exposing the FUB warehouse over stdio.

Tools:
  - describe_schema / describe_table : ground the model in the schema + glossary
  - 8 curated tools                   : deterministic KPI / lookup answers
  - run_select                        : guarded, read-only free-SQL escape hatch

Run: `python -m fub_mcp` or the `fub-mcp` console script. Reads MCP_SQL_* +
GHL_SQL_* from .env (see MCP_SERVER_GUIDE.md). Sister to GHL_API's dcr_mcp.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .db import run_select as _run_select
from .schema import describe_schema as _describe_schema
from .schema import describe_table as _describe_table
from .tools import REGISTRY

mcp = FastMCP("fub-warehouse")

# Schema / grounding
mcp.add_tool(_describe_schema, name="describe_schema")
mcp.add_tool(_describe_table, name="describe_table")

# Curated tools (deterministic) — auto-collected from fub_mcp/tools/*
for _fn in REGISTRY:
    mcp.add_tool(_fn)


@mcp.tool()
def run_select(sql: str, max_rows: int = 200) -> str:
    """Execute an arbitrary READ-ONLY query against dcr_warehouse (schemas `fub`, `analytics`).

    Use this only for questions the curated tools don't cover. Rules:
    - SQL Server T-SQL: use `SELECT TOP (n)`, NOT `LIMIT`; dates via GETUTCDATE(),
      DATEADD, DATEDIFF.
    - A single SELECT / WITH statement only. No writes, DDL, INTO, stored
      procedures, or WAITFOR — the connection is read-only and these are rejected.
    - Prefer the `fub.vw_*` views (call describe_schema first). Rows cap at max_rows.

    Returns a markdown table, or a message starting 'Rejected:' / 'SQL error:'
    that you should read and use to correct the query.
    """
    return _run_select(sql, max_rows)


def main() -> None:
    """Entry point for `python -m fub_mcp` and the `fub-mcp` console script."""
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()
