# FUB_API — Handoff for next session

**Date written**: 2026-05-27
**Read this first**, then `CLAUDE.md` (the deeper canonical reference). Local-only
planning notes live in `nextsteps.md` / `FUB_API_bootstrap_nextsteps.md`
(gitignored — they hold infra details).

This is the **Follow Up Boss** half of the Dana Capital Realty warehouse — the
sibling to GHL_API. Both feed the **same** `dcr_warehouse` SQL Server, in
separate schemas (`ghl`, `fub`), unioned at an `analytics` view layer.

---

## TL;DR for a fresh Claude session

```
Follow Up Boss API (api.followupboss.com/v1)
        │  HTTP Basic (key as user). People 3,320 · Events 3,209 · Deals 228 · + dims
        ▼
scripts/run_all.py  ──►  data/exports/*.csv  ──►  scripts/load_to_sql.py
   (extract + audit + integrity + manifest)            │  (pyodbc, schema-driven)
                                                        ▼
                              SQL Server 2025 on the shared Windows VM
                              dcr_warehouse  (Tailscale; conn vars in .env)
                                                        │
                              ┌─────────────────────────┼───────────────────────┐
                              ▼                                                   ▼
                        fub.* (8 tables) + 3 fub.vw_*            analytics.vw_AllContacts
                        coexists with untouched ghl.*            (UNION ghl + fub = 255,605)
```

Repo: https://github.com/vjpovlitz/FUB_API · branch `main` · **public**.

---

## Current state (what's done)

### Extraction
- All reachable entities pulled to one CSV per table (dataset is tiny — no
  sharding needed; `batch.py` exists but is unused).
- `scripts/export.py` — generic single-endpoint extractor + audit gate.
- `scripts/build_stages.py` — Stages is a union of `/stages` ∪
  `/pipelines[].stages[]` (deal stages live only in the latter).
- `scripts/derive_dims.py` — Sources + Tags derived from People.csv (their
  endpoints are 403/404 on this non-owner key).
- `scripts/run_all.py` — one-command full refresh (extract all → build/derive
  dims → integrity gate → manifest), single exit code.
- Quality gates: `audit_csv.py` (SQL-safety) + `check_integrity.py` (11 FK
  rules, 0 orphans). 100% extract coverage on every reachable entity.

### Warehouse (SQL Server 2025, shared dcr_warehouse, `fub` schema)
| Table | Rows |
|---|--:|
| `fub.People` | 3,320 |
| `fub.Events` | 3,209 |
| `fub.Deals` | 228 |
| `fub.Stages` | 20 |
| `fub.Tags` | 32 |
| `fub.Sources` | 27 |
| `fub.Users` | 4 |
| `fub.Pipelines` | 2 |

All counts reconcile with `data/exports/manifest.json`. `ghl.*` (11 tables + 8
views, 252k contacts) is untouched.

### Analytics layer
- `sql/views/` → `fub.vw_DailyLeadFunnel`, `fub.vw_AgentLeaderboard`,
  `fub.vw_DealsByStage` (auto-applied by `load_to_sql.py`).
- `sql/analytics/vw_AllContacts.sql` → `analytics.vw_AllContacts`: UNION of
  `ghl.Contacts` + `fub.People` (255,605 rows) — proves cross-system joins.
  Applied separately (depends on both schemas).

### Dashboard
- Separate Streamlit app in `dashboard/` (NOT the GHL app). Overview + 4 pages:
  Funnel, Agents, Deals, Cross-System. Reads `fub.*` / `fub.vw_*` / `analytics.*`
  via `dashboard/_db.py`. Deps: `pip install -e ".[dashboard]"`.
  Run: `.venv/bin/streamlit run dashboard/app.py --server.port 8502`.
  Validated via `streamlit.testing.v1.AppTest` (not yet eyeballed in a browser).

### Infra
- `.env` (gitignored) holds `FUB_API_KEY` + `GHL_SQL_*` (shared connection vars,
  same names as GHL_API so loader code is portable).
- Every script reading `GHL_SQL_*` calls `load_dotenv()` first.
- `TrustServerCertificate=yes;Encrypt=no;` is mandatory in every connect string
  (self-signed cert; ODBC Driver 18 defaults to Encrypt=yes).
- **67 unit tests** passing (`pytest tests/ -q`); no live API or DB in tests.

---

## Next-step queue

### Tier 1 — high impact, smallish lift
1. **Incremental/delta sync** — today the loader does a clean DROP+CREATE full
   reload. For a daily refresh, add an `updatedAfter`-style extract + switch the
   loader to a **MERGE-upsert** (GHL's `load_to_sql.py` has the pattern; ours
   does insert + PK-dedup). `batch.py` checkpointing is ready for the watermark.
2. **Scheduling (BUILT — needs install)** — `scripts/refresh_daily.py`
   (run_all → load_to_sql → analytics view → smoke-check, alerts on failure) +
   `launchd/com.dcr.fub-refresh.plist` (4x/day, offset 30 min from GHL). Activate:
   `cp launchd/com.dcr.fub-refresh.plist ~/Library/LaunchAgents/ && launchctl load ...`
   (see CLAUDE.md §13). Tested via --dry-run + --skip-extract.

### Tier 2 — net new capability
3. **Owner-scoped key + X-System-Key** — unblocks live `/tags` + `/leadSources`
   (currently 403) so Sources/Tags can be pulled authoritatively and swap the
   derived dims (they carry `Derived="1"`). Also lifts the 10/window Events limit.
4. **More activity entities** — `notes`, `tasks`, `textMessages`, `em` (emails).
   Same recipe (CLAUDE.md §8); check each endpoint's rate limit + hidden filters.
5. **More cross-system analytics** — `analytics.vw_*` joining `fub` + `ghl`
   (e.g. a unified lead funnel / source ROI across both CRMs).

### Tier 3 — polish
6. **Web-accessible dashboard** (currently localhost), external BI (Power
   BI/Metabase on dcr_warehouse), real cert on the SQL Server (drops the
   TrustServerCertificate requirement).

---

## Things explicitly NOT done

- **Dashboard not browser-verified** — the Streamlit app exists and passes
  `AppTest` (scripts + SQL run clean), but hasn't been eyeballed in a browser,
  and it's localhost-only (no remote serving/auth yet).
- **Live Sources/Tags** — `/sources` 404, `/leadSources` & `/tags` 403 on the
  non-owner key. Derived from People instead. Re-pull once an owner key exists.
- **notes / tasks / textMessages / emails** — deferred Tier-2 entities.
- **Incremental sync** — full reload only; no `updatedAfter` watermark yet.
- **MERGE-upsert** — loader uses insert + PK-dedup, not MERGE.

---

## Watch out for

- **Per-endpoint rate limits differ**: People/Deals 125, but **Events only
  10/window** — the throttle paces Events to ~1 req/s automatically.
- **Stages is two endpoints**: `/stages` returns ONLY person stages; deal-pipeline
  stages live in `/pipelines[].stages[]`. `build_stages.py` unions them. A
  person-only Stages table orphans every `Deals.StageId`.
- **No won/lost deal status**: all `Deals.Status='Active'`. The deal lifecycle is
  the pipeline **stage** — "closed/won" = the deal's StageId maps to a
  `fub.Stages` row with `ClosedStage=1`. The views encode this; don't look for a
  status column.
- **AssignedUserId type**: `People.AssignedUserId` is INT, `Users.UserId` is
  VARCHAR — the agent views CAST to join. Keep the cast if you edit them.
- **People includes Trash**: extracted with `includeTrash=true` (1,229 trashed
  rows). Filter on `Stage` in the warehouse if you want them excluded.
- **Never CREATE/DROP `dcr_warehouse`** (shared, already exists) and **never
  touch `ghl.*`**. The loader connects straight to the DB; only `fub.*` is managed.
- **Public repo**: no Tailnet IP / sa password / API key in tracked files — only
  in `.env` (gitignored), along with the local-only planning docs.

---

## Quick reference — common commands

```bash
# Full refresh of all CSVs (extract → audit → integrity → manifest)
.venv/bin/python scripts/run_all.py

# Verify SQL connection + inventory fub.* and ghl.*
.venv/bin/python scripts/verify_sql_connection.py

# Load into dcr_warehouse.fub (DDL + load all 8 + apply fub.vw_* views)
.venv/bin/python scripts/load_to_sql.py
.venv/bin/python scripts/load_to_sql.py --skip-ddl     # load + views, keep tables
.venv/bin/python scripts/load_to_sql.py --only Users   # POC single table

# Apply the cross-system analytics view (depends on ghl + fub)
#   (run sql/analytics/vw_AllContacts.sql via run_sql_file or sqlcmd)

# One-shot full refresh (extract → load → views → smoke); what launchd runs
.venv/bin/python scripts/refresh_daily.py
.venv/bin/python scripts/refresh_daily.py --skip-extract   # reload from CSVs, ~4s

# Tests
.venv/bin/python -m pytest tests/ -q
```

## How to confirm everything works from scratch

1. VM reachable on the tailnet (the `GHL_SQL_SERVER` host from `.env`).
2. `.venv/bin/python scripts/verify_sql_connection.py` — connection + both schemas.
3. `.venv/bin/python -m pytest tests/ -q` — 67 green.
4. Query `fub.vw_DailyLeadFunnel`, `fub.vw_AgentLeaderboard`, `fub.vw_DealsByStage`
   and `analytics.vw_AllContacts` — all return rows.

If #1 fails: VM off or Tailscale auth expired. If #2 fails: the script's own
diagnostics pinpoint TCP vs auth vs schema.
