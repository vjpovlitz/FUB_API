# MCP server guide — DCR warehouse pattern

How to expose a DCR warehouse schema to an LLM as a **read-only MCP server**, so
a model (Claude Desktop, Claude Code, Cursor, etc.) can answer questions about
the data by calling curated tools instead of you hand-writing SQL.

> **Status / direction (2026-05-28):** The reference implementation already
> exists in the **sister project GHL_API** at `src/dcr_mcp/` (server name
> `dcr-warehouse`, schema `ghl`). **FUB_API does not have an MCP server yet.**
> This doc captures the GHL pattern verbatim and gives the step-by-step to build
> the equivalent **`fub_mcp`** server here (schema `fub` + `analytics`). Either
> project can use this as the canonical recipe.

---

## 1. What this server is (and isn't)

- A **stdio** [FastMCP](https://modelcontextprotocol.io) server. The MCP client
  launches it as a subprocess and talks over stdin/stdout — no network port, no
  web server.
- It connects to the **same `dcr_warehouse`** SQL Server the ETL loads into, but
  logs in with a **dedicated read-only SQL login** so the model can never mutate
  data — even if a code guardrail has a bug.
- It exposes three kinds of tools:
  1. **Schema grounding** — `describe_schema` (glossary + object list) and
     `describe_table` (columns/types). These teach the model what the warehouse
     *means* so it picks the right tool / writes correct T-SQL.
  2. **Curated KPI tools** — one function per common question, each backed by a
     `vw_*` analytics view so answers are deterministic.
  3. **`run_select`** — a guarded, read-only free-SQL escape hatch for questions
     the curated tools don't cover.

**Two safety layers, on purpose:** the read-only login is the hard boundary; the
SQL string validation (`validate_select`) is defense-in-depth so the model gets a
friendly `Rejected: ...` message instead of a raw permission error, and
obviously-destructive intent never reaches the server.

---

## 2. Reference layout (GHL_API `src/dcr_mcp/`)

```
src/dcr_mcp/
├── __init__.py
├── __main__.py        # `from .server import main; main()`  -> python -m dcr_mcp
├── config.py          # read-only conn string from env (MCP_SQL_* + GHL_SQL_*)
├── db.py              # validate_select + run_readonly + to_markdown (guardrails)
├── schema.py          # GLOSSARY + describe_schema / describe_table
├── server.py          # FastMCP("dcr-warehouse"); registers tools; main()
└── tools/
    ├── __init__.py    # imports tool modules so @curated runs; exports REGISTRY
    ├── base.py        # @curated registry + md()/check_date()/check_choice() helpers
    ├── analytics.py   # KPI tools backed by ghl.vw_*
    ├── contacts.py
    ├── conversations.py
    └── opportunities.py
```

Packaging (in `pyproject.toml`):

```toml
[project.optional-dependencies]
mcp = [
    "mcp[cli]>=1.0",
    "pyodbc>=5.0",
]

[project.scripts]
dcr-mcp = "dcr_mcp.server:main"     # console-script entry point

[tool.hatch.build.targets.wheel]
packages = ["src/ghl_api", "src/dcr_mcp"]   # ship the mcp package too
```

---

## 3. The pieces (copy these almost verbatim)

### 3.1 `config.py` — read-only connection

Reuse the project's existing `*_SQL_SERVER` / `*_SQL_DATABASE`, but authenticate
with separate **read-only** credentials. Always keep
`TrustServerCertificate=yes;Encrypt=no;` (self-signed cert + ODBC Driver 18).

```python
QUERY_TIMEOUT_SECONDS = int(os.getenv("MCP_QUERY_TIMEOUT", "30"))  # bound runaway scans
MAX_ROWS_CEILING      = int(os.getenv("MCP_MAX_ROWS", "500"))      # hard row cap to the model

def ro_connection_string() -> str:
    server   = os.environ["GHL_SQL_SERVER"]                 # FUB reuses the same vars
    database = os.getenv("GHL_SQL_DATABASE", "dcr_warehouse")
    user     = os.environ["MCP_SQL_USER"]                   # e.g. dcr_ro
    password = os.environ["MCP_SQL_PASSWORD"]
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};UID={user};PWD={password};DATABASE={database};"
        "TrustServerCertificate=yes;Encrypt=no;"
    )
```

### 3.2 `db.py` — guardrails + execution + markdown (reusable as-is)

- `validate_select(sql)`: single statement only (no `;`); must start with
  `select`/`with`; rejects a forbidden-keyword regex (`insert|update|delete|
  merge|drop|alter|create|truncate|exec|grant|...|into|waitfor|dbcc|kill`) and
  `sp_/xp_` procs.
- `run_readonly(sql, params, max_rows)`: connects as the RO login, sets
  `conn.timeout`, fetches `cap + 1` rows to detect truncation, returns
  `(cols, rows, truncated)`.
- `to_markdown(...)` / `_fmt(...)`: render a compact markdown table; truncates
  long cells, escapes `|`, notes when the row cap was hit.
- `run_select(sql, max_rows)`: `validate_select` → `run_readonly` → `to_markdown`,
  returning `Rejected: ...` or `SQL error: ...` on failure so the model can self-correct.

This module is **schema-agnostic** — copy it into `fub_mcp` unchanged.

### 3.3 `tools/base.py` — the curated registry

```python
REGISTRY: list[Callable[..., str]] = []

def curated(fn):
    """Register fn as a curated MCP tool."""
    REGISTRY.append(fn)
    return fn

def md(sql, params=None, cap=200) -> str:          # run + format, friendly errors
def check_date(value, label) -> str:               # validate ISO 'YYYY-MM-DD'
def check_choice(value, allowed, label) -> str:    # whitelist before f-string interpolation
```

A tool is just a `@curated` function with **type hints** (→ the tool's input
schema) and a **model-facing docstring** (→ the description the model reads to
decide when to call it). Use `Literal[...]` for enum params, and **always**
`check_choice` any value that reaches SQL via f-string (e.g. an `ORDER BY`
column) even though MCP validates `Literal`s — defense in depth. Pass real values
as `?` params, never f-string them.

Example (from `analytics.py`):

```python
AgentSort = Literal["OppsWon", "OppsTotal", "LeadsAssigned", ...]

@curated
def agent_leaderboard(order_by: AgentSort = "OppsWon", limit: int = 20) -> str:
    """Per-agent performance leaderboard (with agent names).
    Use for "top agents by X", "who closed the most deals", "rep activity"."""
    limit = max(1, min(limit, 100))
    order_by = check_choice(order_by, get_args(AgentSort), "order_by")
    sql = ("SELECT TOP (?) u.FullName AS Agent, a.* "
           "FROM ghl.vw_AgentLeaderboard a "
           "LEFT JOIN ghl.Users u ON u.UserId = a.UserId "
           f"ORDER BY a.[{order_by}] DESC")
    return md(sql, [limit], cap=limit)
```

### 3.4 `schema.py` — the glossary (the single most important file)

`GLOSSARY` is a hand-written business dictionary: what each table/view means,
the dialect rules (`SELECT TOP (n)`, `GETUTCDATE()`), which view answers which
question, and gotchas. `describe_schema()` returns the glossary + a live list of
queryable objects (`INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='ghl'`);
`describe_table(name)` validates the name against that list, then returns columns
from `INFORMATION_SCHEMA.COLUMNS`. **A good glossary matters more than more tools.**

### 3.5 `server.py` — wire it up

```python
from mcp.server.fastmcp import FastMCP
from .db import run_select as _run_select
from .schema import describe_schema as _describe_schema, describe_table as _describe_table
from .tools import REGISTRY

mcp = FastMCP("dcr-warehouse")
mcp.add_tool(_describe_schema, name="describe_schema")
mcp.add_tool(_describe_table,  name="describe_table")
for _fn in REGISTRY:
    mcp.add_tool(_fn)

@mcp.tool()
def run_select(sql: str, max_rows: int = 200) -> str:
    """Execute an arbitrary READ-ONLY query ... (rules in the docstring)"""
    return _run_select(sql, max_rows)

def main() -> None:
    mcp.run()   # stdio transport

if __name__ == "__main__":
    main()
```

---

## 4. The read-only SQL login (the hard boundary)

Create a dedicated login that can **read** and nothing else, then point
`MCP_SQL_USER`/`MCP_SQL_PASSWORD` at it. Run once as `sa` (do **not** check the
password into the public repo — it lives only in `.env`):

```sql
-- server-level login
CREATE LOGIN dcr_ro WITH PASSWORD = '<<strong-password>>';

USE dcr_warehouse;
CREATE USER dcr_ro FOR LOGIN dcr_ro;

-- read everything...
ALTER ROLE db_datareader ADD MEMBER dcr_ro;
-- ...but never write or run code
DENY INSERT, UPDATE, DELETE, EXECUTE, ALTER, CREATE TABLE TO dcr_ro;
```

(For FUB, that's enough — `db_datareader` covers all schemas including `fub` and
`analytics`. If you prefer least privilege, grant `SELECT` on just those two
schemas instead of `db_datareader`.)

---

## 5. Registering the server with a client

The server is launched by the client as a subprocess. Use the console script
(`fub-mcp` once you add it to `[project.scripts]`) or `python -m fub_mcp`.

**Claude Code** — project-scoped `.mcp.json` at the repo root (gitignore it if it
contains anything sensitive; this one doesn't — secrets stay in `.env`):

```json
{
  "mcpServers": {
    "fub-warehouse": {
      "command": "/Users/smokestack/Projects/FUB_API/.venv/bin/python",
      "args": ["-m", "fub_mcp"],
      "cwd": "/Users/smokestack/Projects/FUB_API"
    }
  }
}
```

or one-liner: `claude mcp add fub-warehouse -- /path/.venv/bin/python -m fub_mcp`

**Claude Desktop** — `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fub-warehouse": {
      "command": "/Users/smokestack/Projects/FUB_API/.venv/bin/python",
      "args": ["-m", "fub_mcp"]
    }
  }
}
```

**Cursor** — `~/.cursor/mcp.json`, same `command`/`args` shape (Cursor uses a
`servers` array).

The subprocess inherits no shell env, so the server reads `.env` itself
(`config.py` calls `load_dotenv(REPO_ROOT / ".env")`) — make sure `MCP_SQL_USER`,
`MCP_SQL_PASSWORD`, and the `*_SQL_SERVER`/`*_SQL_DATABASE` vars are present there.

---

## 6. Testing

```bash
pip install -e ".[mcp]"

# Inspector UI (lists tools, lets you call them by hand):
.venv/bin/python -m mcp dev -m fub_mcp        # or: mcp dev src/fub_mcp/server.py

# Smoke a tool without a client:
.venv/bin/python -c "from fub_mcp.db import run_select; print(run_select('SELECT TOP 3 PersonId, FirstName FROM fub.People'))"
.venv/bin/python -c "from fub_mcp.schema import describe_schema; print(describe_schema())"
```

Confirm a write is rejected: `run_select("DELETE FROM fub.People")` must return a
`Rejected: ...` string (validation), and even a crafted bypass must fail at the
DB because `dcr_ro` lacks the permission.

---

## 7. Building `fub_mcp` — the adaptation checklist

GHL → FUB is a near-mechanical port. The only real work is the glossary + tools.

| GHL (reference) | FUB equivalent |
|---|---|
| schema `ghl` | schema `fub` (+ `analytics` for cross-system) |
| `dcr-warehouse` / `src/dcr_mcp` | `fub-warehouse` / `src/fub_mcp` |
| `ghl.Contacts`, `ghl.Opportunities`, `ghl.Conversations` | `fub.People`, `fub.Deals`, `fub.Events` |
| `ghl.Users/Pipelines/PipelineStages/Tags` | `fub.Users/Pipelines/Stages/Sources/Tags` |
| `ghl.vw_AgentLeaderboard` | `fub.vw_AgentLeaderboard` |
| `ghl.vw_DailyLeadFunnel` | `fub.vw_DailyLeadFunnel` |
| `ghl.vw_LeadSourceROI` (and others) | `fub.vw_DealsByStage` (+ build more `vw_*` as needed) |
| n/a | `analytics.vw_AllContacts` (cross-system GHL+FUB) |

Steps:
1. `pip install -e ".[mcp]"` after adding the `mcp` extra + `fub-mcp` script +
   `src/fub_mcp` to the wheel packages in `pyproject.toml`.
2. Copy `config.py` (swap nothing — it already reads the shared `GHL_SQL_*` +
   `MCP_SQL_*` vars) and `db.py` (verbatim — schema-agnostic).
3. Write `schema.py` with a **FUB glossary**: the 8 `fub.*` tables (People 3,320 /
   Events 3,209 / Deals 228 / Users / Pipelines / Stages / Sources / Tags), the
   `fub.vw_*` views, `analytics.vw_AllContacts`, and FUB quirks (Trash people,
   no won/lost status → `Stages.ClosedStage`, derived Sources/Tags). Point
   `INFORMATION_SCHEMA` filters at `TABLE_SCHEMA='fub'`.
4. Port `tools/` — start with `analytics.py` tools over `fub.vw_DailyLeadFunnel`,
   `fub.vw_AgentLeaderboard`, `fub.vw_DealsByStage`, plus a `cross_system_*`
   tool over `analytics.vw_AllContacts`. Keep the `@curated` + `Literal` +
   `check_choice` discipline.
5. `server.py` = `FastMCP("fub-warehouse")` + register schema tools + REGISTRY +
   `run_select`. Add `__main__.py`.
6. Create the `dcr_ro` read-only login if it doesn't exist (§4); set
   `MCP_SQL_USER`/`MCP_SQL_PASSWORD` in `.env`.
7. Register with your client (§5) and test (§6).

---

## 8. Conventions to preserve

- **Read-only login is non-negotiable** — never give the MCP server write creds.
- **Never f-string a value into SQL.** Bind with `?`; whitelist identifiers
  (ORDER BY columns) with `check_choice`.
- **Cap rows** (`MAX_ROWS_CEILING`) and **timeout** every query.
- **Glossary first.** Curated tools answer the common 80%; the glossary +
  `run_select` cover the rest. Invest in the glossary.
- **Docstrings are the UI** — write them for the model ("Use this when ...").
- Secrets (`MCP_SQL_PASSWORD`, server IP) live only in `.env`; this repo is public.
