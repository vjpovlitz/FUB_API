"""Load the exported FUB CSVs into PostgreSQL (fub schema).

The Postgres counterpart to scripts/load_to_sql.py. Same contract — column
types/order and PKs come from fub_api.schema (single source of truth), reconcile
row counts against data/exports/manifest.json — but Postgres-native:

  * psycopg (not pyodbc); placeholders %s (not ?)
  * BIT -> Python bool; DATETIME2/DATE -> Python datetime/date objects
  * idempotent reruns via INSERT ... ON CONFLICT ("Pk") DO NOTHING (replaces the
    SQL Server "seen-PK" pre-scan)
  * no staging layer (psycopg adapts typed values directly)

The schema must already exist (apply postgres/sql/create_tables.sql, or pass
--init-schema). This script NEVER creates/drops the database.

Usage:
    .venv/bin/python postgres/load_to_pg.py --init-schema      # create fub.* + load all
    .venv/bin/python postgres/load_to_pg.py                    # load all (tables exist)
    .venv/bin/python postgres/load_to_pg.py --only Users       # one table
    .venv/bin/python postgres/load_to_pg.py --truncate         # TRUNCATE then load

Env: PG_* (see postgres/_pg.py / postgres/.env.example).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for _pg

from _pg import apply_sql_file, connect  # noqa: E402

from fub_api.schema import SCHEMAS, base_type  # noqa: E402

EXPORT_DIR = REPO_ROOT / "data" / "exports"
PG_DIR = Path(__file__).resolve().parent
DDL = PG_DIR / "sql" / "create_tables.sql"
VIEWS_DIR = PG_DIR / "sql" / "views"
MANIFEST = EXPORT_DIR / "manifest.json"


def _convert(val: str, sql_type: str):
    """CSV text -> the Python value psycopg should bind for this PG type.

    Empty string -> NULL. Bad numerics/bits/dates -> NULL (mirrors the lenient
    'never fail the load on a bad value' policy of the SQL Server loader).
    """
    if val == "":
        return None
    bt = base_type(sql_type)
    if bt == "DATETIME2":
        try:
            return datetime.fromisoformat(val.replace("Z", "").strip())
        except ValueError:
            return None
    if bt == "DATE":
        try:
            return date.fromisoformat(val[:10])
        except ValueError:
            return None
    if bt == "BIT":
        return True if val == "1" else (False if val == "0" else None)
    if bt in ("INT", "BIGINT", "SMALLINT", "TINYINT"):
        try:
            return int(val)
        except ValueError:
            return None
    if bt in ("DECIMAL", "NUMERIC", "FLOAT", "REAL", "MONEY"):
        try:
            return float(val)
        except ValueError:
            return None
    return val  # VARCHAR / TEXT


def load_table(conn, table: str, truncate: bool, batch_size: int = 1000) -> int:
    columns, types, pk = SCHEMAS[table]
    csv_path = EXPORT_DIR / f"{table}.csv"
    target = f'fub."{table}"'
    if not csv_path.exists():
        print(f"  {target}: no CSV found ({csv_path.name}) — skipping", flush=True)
        return 0

    cur = conn.cursor()
    if truncate:
        cur.execute(f"TRUNCATE TABLE {target}")

    cols = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    # ON CONFLICT makes reruns idempotent without a pre-scan of existing PKs.
    insert_sql = (f'INSERT INTO {target} ({cols}) VALUES ({placeholders}) '
                  f'ON CONFLICT ("{pk}") DO NOTHING')

    inserted = 0
    t0 = time.monotonic()
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        batch: list[tuple] = []
        for row in reader:
            batch.append(tuple(_convert(row.get(c, ""), types[c]) for c in columns))
            if len(batch) >= batch_size:
                cur.executemany(insert_sql, batch)
                inserted += len(batch)
                batch = []
        if batch:
            cur.executemany(insert_sql, batch)
            inserted += len(batch)

    dt = time.monotonic() - t0
    print(f"  {target:22} {inserted:>7,} rows sent  ({dt:5.1f}s)", flush=True)
    return inserted


def _manifest_rows() -> dict[str, int]:
    if not MANIFEST.exists():
        return {}
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {f["file"]: f["rows"] for f in data.get("files", [])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-schema", action="store_true",
                    help="apply postgres/sql/create_tables.sql first (DROP+CREATE fub.*)")
    ap.add_argument("--truncate", action="store_true", help="TRUNCATE tables before insert")
    ap.add_argument("--skip-views", action="store_true", help="skip postgres/sql/views/*.sql")
    ap.add_argument("--only", help="load only this table (exact name, e.g. Users)")
    ap.add_argument("--batch-size", type=int, default=1000)
    args = ap.parse_args()

    tables = [args.only] if args.only else list(SCHEMAS)
    if args.only and args.only not in SCHEMAS:
        print(f"unknown table {args.only!r}; choices: {', '.join(SCHEMAS)}")
        return 2

    print("=== Connect ===")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version(), current_database(), current_user")
            version, dbname, who = cur.fetchone()
        print(f"  database: {dbname}  (as {who})")
        print(f"  build:    {version.split(',')[0]}")

        if args.init_schema:
            print("\n=== DDL (create fub schema + tables) ===")
            print(f"  applying {DDL.name}")
            apply_sql_file(conn, DDL)

        print("\n=== Load ===")
        for t in tables:
            load_table(conn, t, args.truncate, batch_size=args.batch_size)

        print("\n=== Row counts (fub.* vs manifest) ===")
        manifest = _manifest_rows()
        all_ok = True
        with conn.cursor() as cur:
            for t in tables:
                cur.execute(f'SELECT COUNT(*) FROM fub."{t}"')
                n = cur.fetchone()[0]
                expected = manifest.get(f"{t}.csv")
                if expected is None:
                    tag = "  (no manifest entry)"
                elif expected == n:
                    tag = "  OK"
                else:
                    tag = f"  MISMATCH (manifest={expected:,})"
                    all_ok = False
                print(f"  fub.{t:16} {n:>9,}{tag}")

        if not args.skip_views and not args.only and VIEWS_DIR.exists():
            view_files = sorted(VIEWS_DIR.glob("*.sql"))
            if view_files:
                print("\n=== Views ===")
                for vw in view_files:
                    print(f"  applying {vw.name}")
                    apply_sql_file(conn, vw)

    if not all_ok:
        print("\nWARNING: row counts do not match the manifest — investigate.")
        return 1
    print("\nOK — load complete, counts reconcile with manifest.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
