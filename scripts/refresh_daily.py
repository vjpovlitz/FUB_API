"""Daily refresh orchestrator — one command, one exit code, alert on failure.

Pipeline (each step exits non-zero on failure → RefreshError → alert → exit 1):
  1. run_all.py     extract every entity → audit → integrity gate → manifest
  2. load_to_sql.py full reload into dcr_warehouse.fub (DDL + load + fub.vw_*)
  3. analytics view re-apply analytics.vw_AllContacts (cross-system; needs ghl+fub)
  4. smoke-check    every fub.vw_* and analytics.vw_AllContacts returns rows

This is a FULL refresh: the dataset is tiny (~3.3k people), so we re-extract and
reload rather than doing an incremental/MERGE upsert. The brief DROP+CREATE in
step 2 is the only "downtime" (a few seconds). The zero-downtime upgrade is an
`updatedAfter` incremental extract + a MERGE-upsert loader (see HANDOFF.md) —
note that the API re-extract is the slow part (~12 min: /events is 10/window).

Designed to run unattended via launchd (launchd/com.dcr.fub-refresh.plist):
stdout → logs/refresh-out.log, stderr → logs/refresh-err.log. Failures fire an
alert via fub_api.alerts (configure ALERT_WEBHOOK_URL / ALERT_MACOS in .env).

Usage:
    .venv/bin/python scripts/refresh_daily.py
    .venv/bin/python scripts/refresh_daily.py --dry-run        # print steps only
    .venv/bin/python scripts/refresh_daily.py --skip-extract   # reload from existing CSVs
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from fub_api.alerts import send_alert  # noqa: E402
from load_to_sql import connect, run_sql_file  # noqa: E402

PYTHON = sys.executable
RUN_ALL = REPO_ROOT / "scripts" / "run_all.py"
LOAD_SQL = REPO_ROOT / "scripts" / "load_to_sql.py"
ANALYTICS_VIEW = REPO_ROOT / "sql" / "analytics" / "vw_AllContacts.sql"

# Views that must return rows for the refresh to be considered healthy.
SMOKE_VIEWS = [
    "fub.vw_DailyLeadFunnel",
    "fub.vw_AgentLeaderboard",
    "fub.vw_DealsByStage",
    "analytics.vw_AllContacts",
]


class RefreshError(Exception):
    """A refresh step failed; the message names the step and what went wrong."""


def _run(cmd: list[str], dry_run: bool) -> int:
    print(f"\n$ {' '.join(str(c) for c in cmd)}", flush=True)
    if dry_run:
        return 0
    return subprocess.run(cmd, check=False).returncode


def _smoke_check(dry_run: bool) -> None:
    print("\n--- Smoke-check views ---", flush=True)
    if dry_run:
        for v in SMOKE_VIEWS:
            print(f"  (dry-run) would query {v}")
        return
    db = os.getenv("GHL_SQL_DATABASE", "dcr_warehouse")
    with connect(db) as conn:
        cur = conn.cursor()
        for v in SMOKE_VIEWS:
            try:
                cur.execute(f"SELECT COUNT_BIG(*) FROM {v}")
                n = cur.fetchone()[0]
            except Exception as e:  # noqa: BLE001
                raise RefreshError(f"smoke-check: {v} failed to query ({e})") from e
            if n <= 0:
                raise RefreshError(f"smoke-check: {v} returned 0 rows")
            print(f"  {v:32} {n:>9,} rows  OK", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print steps without running")
    ap.add_argument("--skip-extract", action="store_true",
                    help="skip the API re-extract; reload from existing CSVs")
    args = ap.parse_args()

    started = time.monotonic()
    now = datetime.now(timezone.utc)
    print("=" * 78)
    print(f"FUB daily refresh @ {now.isoformat()}")
    print("=" * 78)

    # 1. Extract everything to CSV (audit + integrity gates inside run_all).
    if args.skip_extract:
        print("\n=== [1/4] Extract — SKIPPED (--skip-extract) ===")
    else:
        print("\n=== [1/4] Extract (run_all.py) ===")
        rc = _run([PYTHON, "-u", str(RUN_ALL)], args.dry_run)
        if rc != 0:
            raise RefreshError(f"extract (run_all.py) failed (rc={rc})")

    # 2. Full reload into dcr_warehouse.fub (DDL + load + fub.vw_* views).
    print("\n=== [2/4] Load into fub.* (load_to_sql.py) ===")
    rc = _run([PYTHON, "-u", str(LOAD_SQL)], args.dry_run)
    if rc != 0:
        raise RefreshError(f"load (load_to_sql.py) failed (rc={rc})")

    # 3. Re-apply the cross-system analytics view (depends on ghl.* + fub.*).
    print("\n=== [3/4] Apply analytics.vw_AllContacts ===")
    if args.dry_run:
        print(f"  (dry-run) would apply {ANALYTICS_VIEW.name}")
    else:
        try:
            with connect(os.getenv("GHL_SQL_DATABASE", "dcr_warehouse")) as conn:
                run_sql_file(conn, ANALYTICS_VIEW)
        except Exception as e:  # noqa: BLE001
            raise RefreshError(f"analytics view apply failed ({e})") from e

    # 4. Smoke-check the views.
    print("\n=== [4/4] Smoke-check ===")
    _smoke_check(args.dry_run)

    dt = time.monotonic() - started
    print(f"\nDONE @ {datetime.now(timezone.utc).isoformat()}  ({dt:.0f}s)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RefreshError as e:
        send_alert("FUB refresh FAILED", f"{e}\nLog: {REPO_ROOT}/logs/refresh-err.log")
        sys.exit(1)
    except Exception:
        send_alert("FUB refresh CRASHED", traceback.format_exc())
        sys.exit(1)
