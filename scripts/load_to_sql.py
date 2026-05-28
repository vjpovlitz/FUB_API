"""Load the exported FUB CSVs into the shared SQL Server warehouse (fub schema).

Writes into the SAME database as GHL_API (dcr_warehouse) under a separate `fub`
schema, alongside the existing `ghl` schema. Connects via pyodbc + ODBC Driver
18 and inserts each CSV with executemany(fast_executemany=True) — effectively a
client-side BULK INSERT that does NOT require the file on the server filesystem
(important: we reach the VM over Tailscale). This is the cross-network
counterpart to sql/load_bulk_insert.sql (which BULK INSERTs files local to the
server via sqlcmd).

Column types/order and PKs come from fub_api.schema (the single source of truth)
so the loader never drifts from the CSVs or the DDL.

IMPORTANT: dcr_warehouse already exists and is shared — this script NEVER
creates or drops the database. The DDL (sql/create_tables.sql) creates the `fub`
schema if missing and DROP+CREATEs the fub.* tables only.

Usage:
    .venv/bin/python scripts/load_to_sql.py              # DDL (recreate fub.*) + load all
    .venv/bin/python scripts/load_to_sql.py --only Users # POC: DDL + load one table
    .venv/bin/python scripts/load_to_sql.py --skip-ddl   # load without recreating tables
    .venv/bin/python scripts/load_to_sql.py --truncate   # TRUNCATE then load (keeps tables)

Env (GHL_SQL_* — names shared with GHL_API so the connection code is portable):
    GHL_SQL_SERVER    e.g. <tailnet-ip-or-host>,1433
    GHL_SQL_USER      e.g. sa
    GHL_SQL_PASSWORD
    GHL_SQL_DATABASE  dcr_warehouse  (must already exist)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from contextlib import suppress
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# Load .env so GHL_SQL_* are picked up without shell exports. Load-bearing — a
# missing load_dotenv() silently falls back to localhost (GHL_API hit this).
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

try:
    import pyodbc
except ImportError:
    print("pyodbc not installed. Run: .venv/bin/pip install pyodbc")
    sys.exit(1)

from fub_api.schema import SCHEMAS, base_type  # noqa: E402

EXPORT_DIR = REPO_ROOT / "data" / "exports"
SQL_DDL = REPO_ROOT / "sql" / "create_tables.sql"
VIEWS_DIR = REPO_ROOT / "sql" / "views"
MANIFEST = EXPORT_DIR / "manifest.json"


def connect(database: str) -> "pyodbc.Connection":
    server = os.getenv("GHL_SQL_SERVER", "localhost,1433")
    user = os.getenv("GHL_SQL_USER", "sa")
    pw = os.getenv("GHL_SQL_PASSWORD", "")
    cs = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};UID={user};PWD={pw};DATABASE={database};"
        f"TrustServerCertificate=yes;Encrypt=no;"
    )
    return pyodbc.connect(cs, autocommit=True)


def split_sql_batches(sql: str) -> list[str]:
    """Split T-SQL on GO (case-insensitive, on its own line)."""
    out: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        if line.strip().upper() == "GO":
            stmt = "\n".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(line)
    tail = "\n".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def run_sql_file(conn: "pyodbc.Connection", path: Path) -> None:
    print(f"  running {path.name}")
    cur = conn.cursor()
    for stmt in split_sql_batches(path.read_text(encoding="utf-8")):
        cur.execute(stmt)


def _convert(val: str, sql_type: str):
    """CSV text -> the python value pyodbc should bind for this SQL type.

    Empty string -> NULL. Bad numerics/bits -> NULL (mirrors the TRY_CONVERT
    NULLIF policy in load_bulk_insert.sql: never fail the load on a bad value).
    """
    if val == "":
        return None
    bt = base_type(sql_type)
    if bt == "DATETIME2":
        # CSV format: 2026-05-27T18:03:29.000Z -> 2026-05-27 18:03:29.000
        return val.rstrip("Z").replace("T", " ")
    if bt == "DATE":
        return val[:10]
    if bt == "BIT":
        return 1 if val == "1" else (0 if val == "0" else None)
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
    return val  # VARCHAR / NVARCHAR / CHAR / NCHAR (incl. NVARCHAR(MAX))


def _input_sizes(columns: list[str], types: dict[str, str]):
    """setinputsizes spec so fast_executemany handles NVARCHAR(MAX) columns
    (e.g. RawJson) without 'String data, right truncation'. None = let pyodbc
    infer. Returns None if no MAX column (no override needed)."""
    sizes = []
    has_max = False
    for c in columns:
        if "MAX" in types[c].upper():
            sizes.append((pyodbc.SQL_WVARCHAR, 0, 0))
            has_max = True
        else:
            sizes.append(None)
    return sizes if has_max else None


def load_table(conn: "pyodbc.Connection", table: str, truncate: bool,
               batch_size: int = 1000) -> int:
    columns, types, pk = SCHEMAS[table]
    csv_path = EXPORT_DIR / f"{table}.csv"
    target = f"fub.{table}"
    if not csv_path.exists():
        print(f"  {target}: no CSV found ({csv_path.name}) — skipping", flush=True)
        return 0

    cur = conn.cursor()
    cur.fast_executemany = True
    sizes = _input_sizes(columns, types)
    if sizes:
        cur.setinputsizes(sizes)

    if truncate:
        cur.execute(f"TRUNCATE TABLE {target}")

    # Idempotent reruns: skip PKs already in the table (unless we just truncated).
    seen: set[str] = set()
    if not truncate:
        with suppress(pyodbc.Error):
            cur.execute(f"SELECT {pk} FROM {target}")
            seen = {str(r[0]) for r in cur.fetchall()}
            if seen:
                print(f"  {target}: {len(seen):,} PKs already present — will skip dups",
                      flush=True)

    placeholders = ",".join(["?"] * len(columns))
    insert_sql = f"INSERT INTO {target} ({','.join(columns)}) VALUES ({placeholders})"

    inserted = skipped = 0
    t0 = time.monotonic()
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        batch: list[tuple] = []
        for row in reader:
            pk_val = (row.get(pk) or "").strip()
            if pk_val and pk_val in seen:
                skipped += 1
                continue
            if pk_val:
                seen.add(pk_val)
            batch.append(tuple(_convert(row.get(c, ""), types[c]) for c in columns))
            if len(batch) >= batch_size:
                cur.executemany(insert_sql, batch)
                inserted += len(batch)
                batch = []
        if batch:
            cur.executemany(insert_sql, batch)
            inserted += len(batch)

    dt = time.monotonic() - t0
    print(f"  {target:18} {inserted:>7,} inserted  "
          f"({skipped:,} dups skipped, {dt:5.1f}s)", flush=True)
    return inserted


def _manifest_rows() -> dict[str, int]:
    if not MANIFEST.exists():
        return {}
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {f["file"]: f["rows"] for f in data.get("files", [])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truncate", action="store_true", help="TRUNCATE tables before insert")
    ap.add_argument("--skip-ddl", action="store_true", help="skip create_tables.sql")
    ap.add_argument("--skip-views", action="store_true", help="skip sql/views/*.sql")
    ap.add_argument("--only", help="load only this table (exact name, e.g. Users)")
    ap.add_argument("--batch-size", type=int, default=1000)
    args = ap.parse_args()

    db = os.getenv("GHL_SQL_DATABASE", "dcr_warehouse")
    tables = [args.only] if args.only else list(SCHEMAS)
    if args.only and args.only not in SCHEMAS:
        print(f"unknown table {args.only!r}; choices: {', '.join(SCHEMAS)}")
        return 2

    print("=== Connect ===")
    # Connect straight to the shared DB — never CREATE DATABASE (it must exist).
    with connect(db) as conn:
        cur = conn.cursor()
        cur.execute("SELECT @@VERSION, DB_NAME(), @@SERVERNAME")
        version, dbname, srv = cur.fetchone()
        print(f"  server:   {srv}")
        print(f"  database: {dbname}")
        print(f"  build:    {version.split(chr(10))[0].strip()}")
        if dbname.lower() != db.lower():
            print(f"  WARNING: connected DB {dbname!r} != requested {db!r}")

        if not args.skip_ddl:
            print("\n=== DDL (create fub schema + tables) ===")
            run_sql_file(conn, SQL_DDL)

        print("\n=== Load ===")
        loaded: dict[str, int] = {}
        for t in tables:
            loaded[t] = load_table(conn, t, args.truncate, batch_size=args.batch_size)

        # --- Reconcile row counts against the manifest ---
        print("\n=== Row counts (fub.* vs manifest) ===")
        manifest = _manifest_rows()
        all_ok = True
        for t in tables:
            cur.execute(f"SELECT COUNT_BIG(*) FROM fub.{t}")
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

        # --- Views (need all tables; skipped for a single-table --only load) ---
        if not args.skip_views and not args.only:
            print("\n=== Views ===")
            view_files = sorted(VIEWS_DIR.glob("*.sql")) if VIEWS_DIR.exists() else []
            if not view_files:
                print("  (no view files in sql/views/)")
            for vw in view_files:
                run_sql_file(conn, vw)

    if not all_ok:
        print("\nWARNING: row counts do not match the manifest — investigate before trusting.")
        return 1
    print("\nOK — load complete, counts reconcile with manifest.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
