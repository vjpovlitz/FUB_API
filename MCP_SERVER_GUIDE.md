# MCP server guide — DCR warehouse pattern

How to expose a DCR warehouse schema to an LLM as a **read-only MCP server**, so
a model (Claude Desktop, Claude Code, Cursor, etc.) can answer questions about
the data by calling curated tools instead of you hand-writing SQL.

> **Status (2026-05-28): BUILT.** `fub_mcp` now exists at `src/fub_mcp/` (server
> name `fub-warehouse`, schemas `fub` + `analytics`, 11 tools, registered in
> `.mcp.json`). It was ported from the reference implementation in the sister
> project **GHL_API** at `src/dcr_mcp/` (`dcr-warehouse`, schema `ghl`). This doc
> remains the canonical recipe: §1–8 explain the pattern, §9–14 the build plan
> and handoff. See CLAUDE.md §14 for the FUB-specific operational notes.

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

---

## 9. Next steps — phased build plan for `fub_mcp`

Each phase is independently shippable and has an acceptance check. Stop at any
phase boundary and you still have something that works. Estimated total: ~half a
day (the loader/views already exist; this is mostly the glossary + tools).

### Phase 0 — Prereqs (~5 min)
- [ ] Confirm the warehouse is reachable: `.venv/bin/python scripts/verify_sql_connection.py`
      lists `fub.*` and `analytics.*`.
- [ ] Confirm the views exist (`fub.vw_DailyLeadFunnel`, `vw_AgentLeaderboard`,
      `vw_DealsByStage`, `analytics.vw_AllContacts`). If not, run
      `scripts/load_to_sql.py` once (it applies the fub views) + apply the
      analytics view.
- **Accept:** both schemas inventory clean.

### Phase 1 — Read-only login (~5 min, likely already done)
- [ ] **Reuse the existing `dcr_ro` login** — it has `db_datareader` on the whole
      `dcr_warehouse`, which already includes the `fub` and `analytics` schemas.
      No new SQL needed; just point FUB's `.env` at it (Phase 2). Only create a
      separate `fub_ro` if you want per-project credentials (§4 has the T-SQL).
- [ ] Add `MCP_SQL_USER=dcr_ro` + `MCP_SQL_PASSWORD=<same as GHL>` to FUB's `.env`.
- **Accept:** `sqlcmd`/pyodbc as `dcr_ro` can `SELECT` from `fub.People` but a
      `DELETE` fails with a permission error.

### Phase 2 — Package skeleton (~20 min)
- [ ] Add to `pyproject.toml`: the `mcp` extra (`mcp[cli]>=1.0`; `pyodbc` is
      already a core dep), `[project.scripts] fub-mcp = "fub_mcp.server:main"`,
      and `src/fub_mcp` in `[tool.hatch.build.targets.wheel] packages`.
- [ ] Create `src/fub_mcp/` with `__init__.py`, `__main__.py`, `config.py`
      (copy GHL's verbatim — it already reads `GHL_SQL_*` + `MCP_SQL_*`), and
      `db.py` (copy verbatim — schema-agnostic).
- [ ] `pip install -e ".[mcp]"`.
- **Accept:** `.venv/bin/python -c "from fub_mcp.db import run_select; print(run_select('SELECT TOP 1 PersonId FROM fub.People'))"`
      returns a markdown row.

### Phase 3 — Glossary + schema tools (~45 min, highest value)
- [ ] Write `src/fub_mcp/schema.py` using the **draft glossary in §11**. Point
      the `INFORMATION_SCHEMA` filters at `TABLE_SCHEMA='fub'` (and add an
      `analytics` branch if you want `describe_table` to cover the cross-system
      view).
- **Accept:** `describe_schema()` prints the glossary + a live object list;
      `describe_table('People')` prints 64 columns.

### Phase 4 — Curated tools (~1–2 h)
- [ ] `tools/base.py` (copy verbatim), `tools/__init__.py` (import your modules).
- [ ] `tools/analytics.py` — port `agent_leaderboard`, `daily_lead_funnel`,
      `deals_by_stage` against the `fub.vw_*` views (see §10 for the full list).
- [ ] `tools/people.py` / `tools/deals.py` — `people_search`, `deal_detail`,
      `event_activity`, `lead_source_breakdown`.
- [ ] `tools/cross_system.py` — `cross_system_contacts` over `analytics.vw_AllContacts`.
- **Accept:** each tool returns sane numbers that reconcile with the dashboard
      (People 3,320 / Deals 228 / Events 3,209).

### Phase 5 — Server + free-SQL (~15 min)
- [ ] `server.py` = `FastMCP("fub-warehouse")` + register the two schema tools +
      `REGISTRY` loop + the `run_select` escape hatch (copy GHL's `server.py`,
      change the name and docstring schema to `fub`).
- **Accept:** `python -m fub_mcp` starts without error;
      `run_select("DELETE FROM fub.People")` returns `Rejected: ...`.

### Phase 6 — Register + test (~15 min)
- [ ] Register with your client (§5) as `fub-warehouse`.
- [ ] `mcp dev -m fub_mcp` — call each tool from the Inspector.
- [ ] Ask the model a real question ("top 3 agents by deals closed", "lead funnel
      for the last 30 days") and confirm it picks the right tool.
- **Accept:** the model answers from tools, not hallucinated SQL.

### Phase 7 — Polish (optional)
- [ ] Add a few unit tests (mirror `tests/test_load.py` style) for
      `validate_select` (rejects writes) and the markdown formatter.
- [ ] Document the server in `CLAUDE.md` (a new "§14 MCP server" section) and
      add `MCP_SQL_*` to the run instructions.
- [ ] Consider an MCP smoke check in `refresh_daily.py` (optional).

---

## 10. Proposed FUB tool catalog

The concrete tools to build in Phase 4. Keep each one `@curated`, `Literal`-typed,
`?`-parameterized, and backed by a view where one exists.

| Tool | Backed by | Use for |
|---|---|---|
| `describe_schema` / `describe_table` | `INFORMATION_SCHEMA` | grounding (always first) |
| `agent_leaderboard(order_by, limit)` | `fub.vw_AgentLeaderboard` ⨝ `fub.Users` | "top agents", "who owns the most leads/deals" |
| `daily_lead_funnel(since, until, source, limit)` | `fub.vw_DailyLeadFunnel` | "funnel last week", "daily conversion" |
| `deals_by_stage()` | `fub.vw_DealsByStage` | "pipeline by stage", "how many deals closed" |
| `lead_source_breakdown(order_by, limit)` | `fub.People` GROUP BY `Source` | "where do leads come from", "best sources" |
| `people_search(query, stage, source, limit)` | `fub.People` | "find a lead by name/email", "leads in stage X" |
| `deal_detail(deal_id)` | `fub.Deals` ⨝ `fub.Stages` | "details of deal N" + its people/agents |
| `event_activity(person_id, type, limit)` | `fub.Events` | "recent activity", "calls/emails for person N" |
| `cross_system_contacts(group_by)` | `analytics.vw_AllContacts` | "total contacts across both CRMs" |
| `run_select(sql, max_rows)` | guarded free SQL | anything the curated tools don't cover |

---

## 11. Draft FUB glossary (paste into `src/fub_mcp/schema.py`)

This is the highest-leverage artifact — it teaches the model the FUB warehouse.
Drop it in as `GLOSSARY` and refine as the schema evolves.

```text
# DCR warehouse — Follow Up Boss (SQL Server, schema `fub`)

CRM data for Dana Capital Realty, extracted from Follow Up Boss. All timestamps
are UTC (columns end in `Utc`). This connection is READ-ONLY. T-SQL dialect: use
`SELECT TOP (n)`, NOT `LIMIT`; date math via `DATEADD`, `DATEDIFF`, `GETUTCDATE()`.
Sister data from GoHighLevel lives in schema `ghl`; the two are unioned in
`analytics.vw_AllContacts`.

## Facts
- `fub.People` (~3,320) — leads/contacts. PersonId (PK), FirstName/LastName/Name,
  Emails/Phones (pipe-delimited), Stage (lead stage), Source (lead source),
  AssignedUserId (owning agent; INTEGER -> join fub.Users.UserId), Tags
  (pipe-delimited), CreatedUtc, UpdatedUtc, LastActivityUtc, 22 Custom* columns,
  RawJson (full record). QUIRK: trashed leads are INCLUDED (Stage = 'Trash');
  filter `Stage <> 'Trash'` for "active" people.
- `fub.Deals` (~228) — transactions/opportunities. DealId (PK), Name, Value,
  PipelineId, StageId (-> fub.Stages WHERE StageKind='Deal'), PrimaryPersonId +
  PersonIds/PersonNames (pipe-delimited; the funnel link), PrimaryUserId +
  UserIds/UserNames, CreatedUtc, CustomClosingDate. QUIRK: FUB has NO won/lost
  status — a deal is "closed" when its StageId maps to a fub.Stages row with
  ClosedStage = 1.
- `fub.Events` (~3,209) — activity log: emails, calls, web visits, etc. EventId
  (PK), PersonId (FK -> People), Type, timestamps. "Engaged" = a person with >=1 event.

## Dimensions
- `fub.Users` (4) — agents/staff. UserId (PK, INT), Name, Email, Role.
- `fub.Pipelines` (2) — deal pipelines. PipelineId (PK), Name, StageCount, StageIds.
- `fub.Stages` (20) — UNIFIED person + deal stages. StageId (PK), Name,
  StageKind ('Person'|'Deal'), PipelineId (null for person stages), ClosedStage
  (1 = a closed deal stage), Color. Deal stages live here, NOT in a person-only list.
- `fub.Sources` (27) — lead sources. DERIVED from People (Derived='1'); not an
  authoritative API pull (the API key is non-owner-scoped).
- `fub.Tags` (32) — tags. PK is TagName (FUB tags have no id). DERIVED from People.

## Analytics views (schema `fub`, prefix `vw_`) — prefer these for KPIs
- `vw_DailyLeadFunnel` — per (LeadDate, LeadSource): LeadsCreated -> EngagedContacts
  -> DealsCreated -> DealsClosed, with EngagedPct/DealPct/ClosedPct.
- `vw_AgentLeaderboard` — per agent (UserId): LeadsAssigned, LeadsLast7/30,
  EventsTotal/Last7, DealsTotal/Closed, PipelineValueOpen/Closed. (People.AssignedUserId
  is INT; the view already handles the join to fub.Users.)
- `vw_DealsByStage` — per stage: StageName, IsClosedStage, DealCount, TotalValue,
  AvgValue, StageOrder.

## Cross-system (schema `analytics`)
- `analytics.vw_AllContacts` (~255,605) — UNION ALL of ghl.Contacts + fub.People,
  normalized: ContactId, SourceSystem ('GoHighLevel'|'FollowUpBoss'), FullName,
  Email, Phone, Source, DateAddedUtc. Use for "contacts across both CRMs".
```

---

## 12. Environment variables (`.env`, gitignored)

| Var | Purpose | Notes |
|---|---|---|
| `GHL_SQL_SERVER` | warehouse host (`<tailnet-ip-or-host>,1433`) | shared name with the loader/dashboard |
| `GHL_SQL_DATABASE` | `dcr_warehouse` | shared |
| `MCP_SQL_USER` | read-only login (e.g. `dcr_ro`) | **not** `sa` |
| `MCP_SQL_PASSWORD` | read-only login password | secret — never commit |
| `MCP_QUERY_TIMEOUT` | per-query timeout seconds (default 30) | optional |
| `MCP_MAX_ROWS` | hard row ceiling to the model (default 500) | optional |

`config.py` calls `load_dotenv` itself because the MCP subprocess inherits no
shell env.

---

## 13. Open decisions to confirm before building

1. **Reuse `dcr_ro` or make `fub_ro`?** Reuse is simpler (already has the grants);
   a separate login gives per-project rotation/audit. Default: **reuse**.
2. **Expose the `analytics` schema?** Recommended — `cross_system_contacts` is a
   compelling tool. Means `describe_table` should also look up `analytics`.
3. **Share one `.mcp.json` or one server per project?** Two servers
   (`ghl-warehouse` + `fub-warehouse`) is cleanest; a model can use both. A future
   unified `dcr-warehouse` server could expose all three schemas — only do that
   if you want a single endpoint.
4. **Ship `.mcp.json` in the repo?** It has no secrets (creds live in `.env`), so
   committing it is fine and makes the server discoverable; gitignore it only if
   you hardcode machine-specific paths you don't want public.

---

## 14. Handoff — start here in a fresh session

**Goal:** build a read-only MCP server (`fub-warehouse`) so an LLM can answer
questions about the FUB warehouse via curated tools. **Nothing is built yet** —
this whole doc is the spec.

**Read first (in order):**
1. This file, top to bottom.
2. The reference implementation in the sister project:
   `/Users/smokestack/Projects/DCR/GHL_API/src/dcr_mcp/` — `server.py`, `db.py`,
   `config.py`, `schema.py`, `tools/base.py`, `tools/analytics.py`. The FUB
   server is a near-mechanical port of these.
3. `CLAUDE.md` §12 (warehouse/views) and §2 (the `fub.*` tables) for the schema.

**Do, in order:** follow §9 Phase 0 → 6. Copy `config.py` + `db.py` + `tools/base.py`
verbatim; write `schema.py` from the §11 glossary; build the §10 tools; wire up
`server.py`; register + test.

**State of the world right now (2026-05-28):**
- Warehouse loaded: `fub.*` (8 tables) + `fub.vw_*` (3 views) + `analytics.vw_AllContacts`,
  all live in the shared `dcr_warehouse`. Loader: `scripts/load_to_sql.py`.
- `pyodbc` is already a core dependency; ODBC Driver 18 is installed.
- The `dcr_ro` read-only login exists (created during GHL's MCP build) and already
  covers the `fub`/`analytics` schemas — reuse it.
- The repo is **public** — keep all secrets in `.env` (gitignored).

**Definition of done:** `python -m fub_mcp` starts; the Inspector lists
`describe_schema`, the §10 tools, and `run_select`; a write via `run_select` is
rejected; and the model answers "top agents by deals closed" + "lead funnel last
30 days" correctly from the tools, with numbers matching the dashboard.

**Gotchas (FUB-specific):** trashed people are in `fub.People` (filter
`Stage <> 'Trash'`); deals have no won/lost status (use `fub.Stages.ClosedStage`);
`People.AssignedUserId` is INT (cast when joining `fub.Users.UserId`); Sources/Tags
are derived, not authoritative.
