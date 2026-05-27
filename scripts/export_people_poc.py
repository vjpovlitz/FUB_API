"""POC: extract People to a SQL-Server-shaped CSV, then run the audit gate.

Pulls up to --max-rows people (default 100), maps + sanitizes each row, writes
data/exports/People.csv (UTF-8 BOM, CRLF, QUOTE_MINIMAL), then runs
scripts/audit_csv.py as a hard gate. Non-zero exit = bad data, do not load.

Read-only against FUB. Safe to re-run (overwrites the CSV).
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make src/ importable when run as a script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fub_api.client import FUBClient  # noqa: E402
from fub_api.mappers import PEOPLE_COLUMNS, map_person  # noqa: E402

EXPORT_DIR = ROOT / "data" / "exports"
OUT_PATH = EXPORT_DIR / "People.csv"


def _now_utc_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _mask(s: str) -> str:
    return s[:4] + "***" if len(s) > 4 else s


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf")  # BOM first
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=PEOPLE_COLUMNS,
            lineterminator="\r\n",
            quoting=csv.QUOTE_MINIMAL,
            extrasaction="ignore",
        )
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in PEOPLE_COLUMNS})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rows", type=int, default=100)
    args = ap.parse_args()

    extracted_at = _now_utc_iso()
    rows: list[dict] = []
    next_token: str | None = None

    with FUBClient.from_env() as client:
        while len(rows) < args.max_rows:
            page_limit = min(100, args.max_rows - len(rows))
            people, next_token = client.people.page(
                limit=page_limit, next_token=next_token
            )
            if not people:
                break
            for p in people:
                rows.append(map_person(p, extracted_at=extracted_at))
            print(
                f"  fetched {len(people):>3}  total={len(rows):>4}  "
                f"burst_rem={client.throttle.burst_remaining}"
            )
            if next_token is None:
                break

        print(f"\nThrottle stats: {client.throttle.stats()}")

    rows = rows[: args.max_rows]
    write_csv(rows, OUT_PATH)
    print(f"\nWrote {len(rows)} rows -> {OUT_PATH}")

    # PII-masked sample
    if rows:
        s = rows[0]
        print("\nSample row (masked):")
        print(f"  PersonId={s['PersonId']}  Name={s['Name']}  "
              f"Email={_mask(s['PrimaryEmail'])}  Phone={_mask(s['PrimaryPhone'])}  "
              f"Stage={s['Stage']}  CreatedUtc={s['CreatedUtc']}")

    # ---- audit gate ----
    print(f"\n{'=' * 78}\nRunning audit gate...\n{'=' * 78}")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_csv.py"), str(OUT_PATH)]
    )
    if result.returncode != 0:
        print("\nAUDIT FAILED — see findings above. Not safe to load.")
        sys.exit(1)
    print("\nPOC complete: extract + audit both green.")


if __name__ == "__main__":
    main()
