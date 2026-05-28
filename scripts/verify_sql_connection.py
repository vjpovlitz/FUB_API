"""Verify the SQL Server connection + report schema state for the FUB warehouse.

FUB writes into the SAME shared database (dcr_warehouse) as GHL_API, under a
separate `fub` schema alongside the existing `ghl` schema. This script:
  1. TCP-probes the server (helps debug Tailscale / firewall)
  2. Connects via ODBC Driver 18 (TrustServerCertificate=yes;Encrypt=no — the
     server uses a self-signed cert; Driver 18 defaults to Encrypt=yes)
  3. Inventories BOTH fub.* and ghl.* tables, so you can confirm the two source
     systems coexist in one warehouse

Reads GHL_SQL_* env vars (shared connection vars; the names are kept identical
to GHL_API so loader/verifier code is portable). Exit codes:
  0 = connected, fub schema present + populated
  1 = connection failed (with hint)
  2 = connected but fub schema missing or empty
"""
from __future__ import annotations

import os
import socket
import sys
import time
from contextlib import suppress

try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc not installed. Run: .venv/bin/pip install pyodbc")
    sys.exit(1)

# Load .env so GHL_SQL_* are picked up without shell exports. The GHL_API repo
# hit a bug where a missing load_dotenv() silently fell back to localhost — so
# this call is load-bearing, not optional.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _inventory(cur: "pyodbc.Cursor", schema: str) -> list[str]:
    cur.execute(
        "SELECT TABLE_SCHEMA + '.' + TABLE_NAME AS FullName "
        "FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ? ORDER BY TABLE_NAME",
        (schema,),
    )
    return [r[0] for r in cur.fetchall()]


def _print_counts(cur: "pyodbc.Cursor", tables: list[str]) -> None:
    print(f"  {'Table':32} {'Rows':>12}  Latest ExtractedAtUtc")
    print(f"  {'-' * 32} {'-' * 12}  {'-' * 25}")
    for t in tables:
        cur.execute(f"SELECT COUNT_BIG(*) FROM {t}")
        n = cur.fetchone()[0]
        ts = "—"
        with suppress(pyodbc.Error):
            cur.execute(f"SELECT MAX(ExtractedAtUtc) FROM {t}")
            r = cur.fetchone()
            if r and r[0] is not None:
                ts = str(r[0])[:25]
        print(f"  {t:32} {n:>12,}  {ts}")


def main() -> int:
    server = env("GHL_SQL_SERVER", "localhost,1433")
    user = env("GHL_SQL_USER", "sa")
    pw = env("GHL_SQL_PASSWORD", "")
    db = env("GHL_SQL_DATABASE", "dcr_warehouse")

    print("=" * 70)
    print("SQL Server connection check (FUB → shared dcr_warehouse)")
    print("=" * 70)
    print(f"  GHL_SQL_SERVER:   {server}")
    print(f"  GHL_SQL_USER:     {user}")
    print(f"  GHL_SQL_DATABASE: {db}")
    print(f"  GHL_SQL_PASSWORD: {'(set, ' + str(len(pw)) + ' chars)' if pw else '(EMPTY)'}")

    # --- Step 1: TCP reachability (Tailscale / firewall debugging) ---
    host, _, port_str = server.partition(",")
    port = int(port_str) if port_str else 1433
    print(f"\nStep 1: TCP probe to {host}:{port}")
    t0 = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((host, port))
        print(f"  OK  reachable ({(time.monotonic() - t0) * 1000:.0f} ms)")
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"  FAIL  {type(e).__name__}: {e}")
        print("\n  Diagnostics:")
        if "refused" in str(e).lower():
            print("    - SQL Server not running or not listening on port", port)
            print("    - Check SQL Server Configuration Manager → TCP/IP enabled, static 1433")
        elif "timed out" in str(e).lower():
            print("    - Network path blocked (likely Windows Firewall on the VM)")
            print("    - Verify Tailscale is up on both ends: `tailscale status`")
        elif "Name or service" in str(e) or "not known" in str(e).lower():
            print(f"    - Hostname {host!r} not resolving (try the raw Tailnet IP)")
        return 1
    finally:
        with suppress(Exception):
            sock.close()

    # --- Step 2: ODBC connect ---
    cs = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server};"
        f"UID={user};PWD={pw};DATABASE={db};"
        f"TrustServerCertificate=yes;Encrypt=no;"
    )
    print("\nStep 2: ODBC connect")
    t0 = time.monotonic()
    try:
        conn = pyodbc.connect(cs, timeout=8)
    except pyodbc.Error as e:
        print(f"  FAIL  {e}")
        msg = str(e).lower()
        if "login failed" in msg:
            print("  Diagnostics: wrong sa password, or Mixed Mode auth not enabled on the VM.")
        elif "cannot open database" in msg:
            print(f"  Diagnostics: database {db!r} does not exist. It is expected to ALREADY exist")
            print("    (shared with GHL_API) — do not create it here. Check GHL_SQL_DATABASE.")
        return 1
    print(f"  OK  connected ({(time.monotonic() - t0) * 1000:.0f} ms)")

    cur = conn.cursor()
    cur.execute("SELECT @@VERSION, DB_NAME(), @@SERVERNAME")
    version, dbname, srv = cur.fetchone()
    print(f"\n  Server: {srv}")
    print(f"  DB:     {dbname}")
    print(f"  Build:  {version.split(chr(10))[0].strip()}")

    # --- Step 3: fub schema (this project's tables) ---
    print("\nStep 3: fub.* tables (this project)")
    fub_tables = _inventory(cur, "fub")
    if fub_tables:
        _print_counts(cur, fub_tables)
    else:
        print("  (no tables in fub schema yet — run scripts/load_to_sql.py)")

    # --- Step 4: ghl schema (sister project; confirm coexistence) ---
    print("\nStep 4: ghl.* tables (sister project — should be untouched)")
    ghl_tables = _inventory(cur, "ghl")
    if ghl_tables:
        for t in ghl_tables:
            print(f"    {t}")
    else:
        print("  (no ghl tables — that's fine if GHL_API hasn't loaded here)")

    if not fub_tables:
        print("\n  fub schema empty. Next: .venv/bin/python scripts/load_to_sql.py")
        return 2
    print("\nOK  fub schema present in the shared warehouse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
