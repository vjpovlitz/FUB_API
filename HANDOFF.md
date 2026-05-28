# FUB_API — Handoff for next session

**Date written**: 2026-05-28
**Read this first**, then `CLAUDE.md` (the deeper canonical reference) and
`MCP_SERVER_GUIDE.md` (the MCP server pattern + backlog). Local-only planning
notes live in `nextsteps.md` / `FUB_API_bootstrap_nextsteps.md` / `task.md`
(gitignored — infra details / scratch).

This is the **Follow Up Boss** half of the Dana Capital Realty warehouse — the
sibling to GHL_API. Both feed the **same** `dcr_warehouse` SQL Server, in
separate schemas (`ghl`, `fub`), unioned at an `analytics` view layer.

---

## TL;DR for a fresh Claude session

```
Follow Up Boss API (api.followupboss.com/v1)
        │  HTTP Basic (key as user). 3 core + 3 activity facts + 5 dims
        ▼
scripts/run_all.py  ──►  data/exports/*.csv  ──►  scripts/load_to_sql.py
   (extract + audit + integrity + manifest)            │  (pyodbc, schema-driven)
                                                        ▼
                              SQL Server on the shared Windows VM (Tailscale)
                              dcr_warehouse  (conn vars in .env)
                                                        │
                ┌───────────────────────────────────────┼───────────────────────┐
                ▼                                         ▼                        ▼
        fub.* (11 tables) + 3 fub.vw_*       analytics.vw_AllContacts     src/fub_mcp (MCP)
        coexists with untouched ghl.*        (UNION ghl + fub ≈ 255,600)  read-only, 14 tools
                                                                          ▲
                                                  Claude Desktop / Claude Code / Cursor
                                                  ask questions in plain English
```

Repo: https://github.com/vjpovlitz/FUB_API · branch `main` · **public**.

---

## Current state (what's done)

### Extraction
- `scripts/export.py` — generic single-endpoint extractor + audit gate. Entities:
  `people · deals · events · tasks · notes · calls · users · pipelines`.
- `scripts/build_stages.py` — Stages = `/stages` ∪ `/pipelines[].stages[]`.
- `scripts/derive_dims.py` — Sources + Tags derived from People.csv (403/404 on
  this non-owner key).
- `scripts/run_all.py` — one-command full refresh (extract all → build/derive
  dims → integrity gate → manifest), single exit code.
- Quality gates: `audit_csv.py` (SQL-safety) + `check_integrity.py` (**15 FK
  rules, 0 orphans**). 100% extract coverage on every reachable entity.

### Warehouse (shared dcr_warehouse, `fub` schema — 11 tables)
| Table | Rows | Notes |
|---|--:|---|
| `fub.People` | 3,327 | incl. Trash; 64 cols + RawJson |
| `fub.Calls` | 57,231 | **activity fact (new)**; userId -1 = system/automated |
| `fub.Notes` | 9,238 | **activity fact (new)**; CreatedById -1 = system |
| `fub.Events` | 3,211 | activity log |
| `fub.Tasks` | 2,850 | **activity fact (new)**; set/completed/missed |
| `fub.Deals` | 228 | no won/lost status — use Stages.ClosedStage |
| `fub.Tags` | 32 | derived |
| `fub.Sources` | 27 | derived |
| `fub.Stages` | 20 | unified person+deal |
| `fub.Users` | 4 | agents (ids 1-4) |
| `fub.Pipelines` | 2 | |

All counts reconcile with `data/exports/manifest.json`. `ghl.*` (11 tables + 8
views, 252k contacts) is untouched.

### Analytics layer
- `sql/views/` → `fub.vw_DailyLeadFunnel`, `fub.vw_AgentLeaderboard`,
  `fub.vw_DealsByStage` (auto-applied by `load_to_sql.py`).
- `sql/analytics/vw_AllContacts.sql` → `analytics.vw_AllContacts`: UNION of
  `ghl.Contacts` + `fub.People` (≈255,600 rows). Applied separately (both schemas).

### MCP server — `src/fub_mcp/` (`fub-warehouse`) — NEW
- Read-only FastMCP **stdio** server so an LLM answers warehouse questions via
  tools instead of hand-written SQL. Full design/recipe: `MCP_SERVER_GUIDE.md`;
  ops notes: CLAUDE.md §14.
- **Safety, two layers**: logs in as the read-only `dcr_ro` SQL login (reused
  from GHL — `db_datareader` covers `fub`+`analytics`; verified it *cannot* write)
  **and** a `validate_select` guardrail (single SELECT/WITH only).
- **14 tools**: `describe_schema`/`describe_table`; curated `agent_leaderboard`,
  `daily_lead_funnel`, `deals_by_stage`, `lead_source_breakdown`, `people_search`,
  `event_activity`, `deal_detail`, `cross_system_contacts`, `task_summary`,
  `call_activity`, `note_activity`; and guarded `run_select`.
- Registered: repo `.mcp.json` (Claude Code) + `~/Library/.../claude_desktop_config.json`
  (Claude Desktop). Run by hand: `.venv/bin/python -m mcp dev -m fub_mcp`.
- Creds: `MCP_SQL_USER=dcr_ro` / `MCP_SQL_PASSWORD` in `.env` (copied from GHL).

### Dashboard
- Separate Streamlit app in `dashboard/` (NOT the GHL app). **DCR-branded**
  (brand blue #005dcf / navy, Saira+Montserrat, white logo) with a **liquid-glass
  sidebar** (`st.navigation` router, login dialog + Account/Settings **placeholders**).
  Pages: Overview, Funnel, Agents, Deals, Cross-System. Reads `fub.*`/`fub.vw_*`/
  `analytics.*` via `dashboard/_db.py`. Deps: `pip install -e ".[dashboard]"`.
  Run: `.venv/bin/streamlit run dashboard/app.py --server.port 8502`. Viewed in a
  browser; login/account/settings are non-functional placeholders.

### Scheduling
- `scripts/refresh_daily.py` (run_all → load_to_sql → analytics view → smoke +
  alerts) + `launchd/com.dcr.fub-refresh.plist` (9:30/13:30/16:30/21:30, offset
  from GHL). **Installed + loaded** (`launchctl list | grep dcr` shows both jobs).
  Caveat: a run fails if the VM is paused/unreachable at fire time (the VM
  auto-pauses — see "Watch out for").

### Infra
- `.env` (gitignored): `FUB_API_KEY`, `GHL_SQL_*` (shared conn vars), `MCP_SQL_*`.
- `TrustServerCertificate=yes;Encrypt=no;` mandatory in every connect string.
- **104 unit tests** passing (`pytest tests/ -q`); no live API/DB in tests.

---

## Next-iteration queue

### Tier 1 — high impact
1. **Incremental/delta sync + MERGE-upsert** — the full DROP+CREATE reload now
   re-extracts **57k calls** every run; the API re-extract is the slow part.
   Add an `updatedAfter`-style extract + switch the loader from insert+PK-dedup
   to a **MERGE-upsert** (GHL's loader has the pattern; `batch.py` checkpointing
   is ready for the watermark). Biggest single win now that volume is real.
2. **Surface the new activity facts in the dashboard** — a "Rep Activity" page:
   tasks set/completed/missed, calls (in/out/talk-min), notes per agent over a
   date range. The MCP tools (`task_summary`/`call_activity`/`note_activity`)
   already encode the logic — mirror it in `dashboard/pages/`.

### Tier 2 — net new capability
3. **Appointments** (`/appointments` 41 + `/appointmentTypes` 2 +
   `/appointmentOutcomes` 3) — recipe is proven; invitees is an array of
   {userId, personId, name} (capture count + names, no FK). Low volume, rounds
   out "activity".
4. **`/textMessages`** — returns **400 without a filter**; likely requires a
   `personId` (per-person) query. Needs an investigation + a per-person or
   bulk-by-day extract strategy before it's worth wiring. `/em`/`/emails` are
   404/not-exposed.
5. **Owner-scoped key + X-System-Key** — unblocks live `/tags` + `/leadSources`
   (currently 403; swap the `Derived="1"` dims) and lifts the Events 10/window cap.
6. **More cross-system analytics** — `analytics.vw_*` joining `fub`+`ghl` (unified
   lead funnel / source ROI across both CRMs); add matching MCP tools.
7. **More MCP tools / unified server** — add tools as questions arise; consider a
   single `dcr-warehouse` MCP exposing `ghl`+`fub`+`analytics` (the two
   `src/*_mcp/` packages are near-identical).

### Tier 3 — polish
8. **Real dashboard auth** (login is a placeholder) + web-accessible serving +
   external BI (Power BI/Metabase) + a real cert on SQL Server (drops the
   TrustServerCertificate requirement).

---

## Things explicitly NOT done
- **Incremental sync / MERGE-upsert** — full reload only; no `updatedAfter` watermark.
- **Appointments / textMessages / emails** — deferred (see Tier 2 #3, #4).
- **Live Sources/Tags** — derived from People (non-owner key). Re-pull with an owner key.
- **Dashboard auth + remote serving** — login/account/settings are placeholders; localhost only.
- **New activity facts not yet in the dashboard** — queryable via MCP / SQL only so far.

---

## Watch out for
- **`-1` = the FUB system/automation actor.** Appears in `Tasks.CreatedById`,
  `Notes.CreatedById`, and `Calls.UserId` (auto-created records / automated calls).
  It has **no `fub.Users` row**, so those FKs are intentionally **not** integrity-
  enforced. In queries use `ISNULL`/`CASE` (the MCP tools label it `(system/...)`).
- **`AssignedUserId`/`UserId` are INT, `Users.UserId` is VARCHAR** — CAST when
  joining (the agent views + MCP tools already do).
- **No won/lost deal status** — `Deals.Status='Active'` always; "closed" = the
  deal's StageId maps to a `fub.Stages` row with `ClosedStage=1`.
- **People includes Trash** (`includeTrash=true`) — filter `Stage <> 'Trash'` for active.
- **Stages is two endpoints** — person stages from `/stages`, deal stages from
  `/pipelines[].stages[]`; `build_stages.py` unions them.
- **Per-endpoint rate limits differ** — People/Deals 125, **Events 10/window**;
  the throttle paces automatically.
- **The VM auto-pauses.** After a pause/reboot, SQL Server (MSSQLSERVER, set to
  Automatic Delayed Start) can take ~2 min to bind 1433 — connections time out
  until then. `verify_sql_connection.py` distinguishes TCP-vs-auth-vs-schema.
- **Never CREATE/DROP `dcr_warehouse`** (shared) and **never touch `ghl.*`**.
- **Public repo** — no Tailnet IP / sa password / API key in tracked files; only
  in `.env` + `.claude/` (both gitignored) and the local-only planning docs.
- **Claude Desktop caches the MCP subprocess** — after changing `src/fub_mcp/`
  code (e.g. new tools), fully quit (⌘Q) and reopen Desktop to respawn it. New
  *data* needs no restart (tools query the live DB).

---

## Quick reference — common commands

```bash
# Full refresh of all CSVs (extract → audit → integrity → manifest)
.venv/bin/python scripts/run_all.py

# One entity (paginate → map → audit gate)
.venv/bin/python scripts/export.py --entity tasks        # or notes / calls / people / ...
.venv/bin/python scripts/export.py --entity calls --max-rows 50   # POC

# Verify SQL connection + inventory fub.* and ghl.*
.venv/bin/python scripts/verify_sql_connection.py

# Load into dcr_warehouse.fub (DDL recreate + load all 11 + apply fub.vw_*)
.venv/bin/python scripts/load_to_sql.py
.venv/bin/python scripts/load_to_sql.py --skip-ddl       # load + views, keep tables
.venv/bin/python scripts/load_to_sql.py --only Tasks     # single table

# MCP server (read-only)
.venv/bin/python -m fub_mcp                              # stdio (blocks; clients spawn this)
.venv/bin/python -m mcp dev -m fub_mcp                   # Inspector UI to call tools

# One-shot full refresh (extract → load → views → smoke); what launchd runs
.venv/bin/python scripts/refresh_daily.py --skip-extract # reload from CSVs

# Tests
.venv/bin/python -m pytest tests/ -q                     # 104
```

## How to confirm everything works from scratch
1. VM reachable on the tailnet; SQL Server up (`tailscale ping 100.x`, then
   `verify_sql_connection.py`). If it times out right after a reboot, wait ~2 min
   (Delayed Start) and retry.
2. `.venv/bin/python -m pytest tests/ -q` — **104 green**.
3. Query `fub.vw_*` + `analytics.vw_AllContacts` — all return rows.
4. MCP smoke: `.venv/bin/python -c "from fub_mcp.tools.tasks import task_summary; print(task_summary('VaChelle'))"`
   — returns a set/completed/missed row.

If #1 fails: VM off/paused or Tailscale auth expired. If #2 fails: the script's
own diagnostics pinpoint TCP vs auth vs schema.
