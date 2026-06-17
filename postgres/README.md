# `postgres/` — PostgreSQL migration kit

Everything Postgres-specific for moving `dcr_warehouse` off SQL Server lives here.
The full plan, decisions, and rationale are in **`../DB_MIGRATION.md`** — this is
the working folder it refers to.

## Contents

| Path | What it is | Status |
|---|---|---|
| `generate_pg_ddl.py` | Emits `sql/create_tables.sql` from `fub_api.schema` (the single source of truth). Quoted PascalCase + PG types; no staging layer. | ✅ done |
| `sql/create_tables.sql` | Generated DDL: `fub.*` 11 typed tables (DROP+CREATE, PK constraints). | ✅ generated |
| `_pg.py` | Shared conn helper: `pg_url()` / `connect()` (rw = `dcr`, ro = `dcr_ro`) + `apply_sql_file()`. | ✅ done |
| `load_to_pg.py` | psycopg loader: CSV → `fub.*`, `ON CONFLICT DO NOTHING`, reconciles vs `manifest.json`. | ✅ done (needs a live DB to run) |
| `.env.example` | `PG_*` keys to copy into the repo `.env`. | ✅ |
| `sql/views/` | Rewritten Postgres views (`fub.vw_*`, `analytics.*`). | ⬜ TODO (DB_MIGRATION.md §8) |
| `verify_pg_connection.py` | TCP+psycopg probe + schema inventory. | ⬜ TODO |

Still on the SQL Server side / not yet ported: the **MCP server** (`src/fub_mcp/`),
the **dashboard** (`dashboard/_db.py`), and `scripts/refresh_daily.py`. See
DB_MIGRATION.md §7.

## Type mapping (SQL Server → Postgres)

`NVARCHAR(n)`→`VARCHAR(n)` · `NVARCHAR(MAX)`→`TEXT` · `INT`→`INTEGER` ·
`BIGINT`→`BIGINT` · `BIT`→`BOOLEAN` · `DATETIME2(3)`→`TIMESTAMP(3)` · `DATE`→`DATE`.
Identifiers stay PascalCase via double-quoting (Postgres lowercases unquoted ones).

## Quick start

```bash
# 0. Deps (psycopg)
.venv/bin/pip install -e ".[postgres]"

# 1. Provision the VPS: Postgres 16 + Tailscale + roles/schemas (DB_MIGRATION.md §9)
#    then copy postgres/.env.example keys into .env and fill PG_HOST / passwords.

# 2. (Re)generate the DDL after any mapper/schema change
.venv/bin/python postgres/generate_pg_ddl.py

# 3. Create the schema on the VPS — either path:
psql "$PG_URL" -f postgres/sql/create_tables.sql
#   ...or let the loader do it:
.venv/bin/python postgres/load_to_pg.py --init-schema

# 4. Load fub.* from the existing CSVs (data/exports/) + reconcile vs manifest
.venv/bin/python postgres/load_to_pg.py            # all tables
.venv/bin/python postgres/load_to_pg.py --only Users   # one table (POC)
```

The generator + loader were validated offline (DDL parses to 23 statements;
`_convert` coerces every type incl. timestamps/dates/bools). The loader itself
needs the live VPS Postgres to run end-to-end.

## Notes

- **Never** create/drop the database — it's shared (`ghl.*` lives here too). The
  DDL only touches `fub.*`.
- `ghl.*` is migrated by GHL_API (or a one-shot `pgloader`); see DB_MIGRATION.md §6/§11.
- Idempotent: rerun the loader freely — `ON CONFLICT ("Pk") DO NOTHING` skips dups;
  `--truncate` clears + reloads.
