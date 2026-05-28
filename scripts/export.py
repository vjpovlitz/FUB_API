"""Generic non-batched extractor: pull an entity to a SQL-Server-shaped CSV,
then run the audit gate.

    .venv/bin/python scripts/export.py --entity deals
    .venv/bin/python scripts/export.py --entity people --max-rows 100
    .venv/bin/python scripts/export.py --entity events --max-rows 50 --page-limit 25

Follows DATA_RULES: UTF-8 BOM, CRLF, QUOTE_MINIMAL, sanitized fields, audit
gate (non-zero exit on any issue). For high-volume / tightly rate-limited
entities that need resume, use batch.py instead — this path holds everything
in memory and writes one file.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fub_api.client import FUBClient  # noqa: E402
from fub_api.mappers import (  # noqa: E402
    CALL_COLUMNS,
    DEAL_COLUMNS,
    EVENT_COLUMNS,
    NOTE_COLUMNS,
    PEOPLE_COLUMNS,
    PIPELINE_COLUMNS,
    TASK_COLUMNS,
    USER_COLUMNS,
    map_call,
    map_deal,
    map_event,
    map_note,
    map_person,
    map_pipeline,
    map_task,
    map_user,
)

EXPORT_DIR = ROOT / "data" / "exports"

# entity -> (client resource attr, columns, mapper, output filename)
# Single-endpoint live pulls only. Stages is a two-endpoint union (/stages +
# /pipelines[].stages[]) built by scripts/build_stages.py. Sources/Tags are
# DERIVED dims built by scripts/derive_dims.py.
REGISTRY = {
    "people": ("people", PEOPLE_COLUMNS, map_person, "People.csv"),
    "deals": ("deals", DEAL_COLUMNS, map_deal, "Deals.csv"),
    "events": ("events", EVENT_COLUMNS, map_event, "Events.csv"),
    "tasks": ("tasks", TASK_COLUMNS, map_task, "Tasks.csv"),
    "notes": ("notes", NOTE_COLUMNS, map_note, "Notes.csv"),
    "calls": ("calls", CALL_COLUMNS, map_call, "Calls.csv"),
    "users": ("users", USER_COLUMNS, map_user, "Users.csv"),
    "pipelines": ("pipelines", PIPELINE_COLUMNS, map_pipeline, "Pipelines.csv"),
}


def _now_utc_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def write_csv(rows: list[dict], columns: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf")  # BOM first
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=columns,
            lineterminator="\r\n",
            quoting=csv.QUOTE_MINIMAL,
            extrasaction="ignore",
        )
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entity", required=True, choices=sorted(REGISTRY))
    ap.add_argument("--max-rows", type=int, default=None)
    ap.add_argument("--page-limit", type=int, default=100,
                    help="rows per request (lower = gentler on rate limits)")
    args = ap.parse_args()

    attr, columns, mapper, filename = REGISTRY[args.entity]
    out_path = EXPORT_DIR / filename
    extracted_at = _now_utc_iso()

    rows: list[dict] = []
    next_token: str | None = None
    cap = args.max_rows if args.max_rows is not None else float("inf")

    with FUBClient.from_env() as client:
        resource = getattr(client, attr)
        while len(rows) < cap:
            page_limit = min(args.page_limit, 100)
            if args.max_rows is not None:
                page_limit = min(page_limit, args.max_rows - len(rows))
            api_rows, next_token = resource.page(limit=page_limit, next_token=next_token)
            if not api_rows:
                break
            rows.extend(mapper(r, extracted_at=extracted_at) for r in api_rows)
            print(f"  fetched {len(api_rows):>3}  total={len(rows):>5}  "
                  f"burst_rem={client.throttle.burst_remaining}")
            if next_token is None:
                break
        print(f"\nThrottle stats: {client.throttle.stats()}")

    if args.max_rows is not None:
        rows = rows[: args.max_rows]
    write_csv(rows, columns, out_path)
    print(f"\nWrote {len(rows)} rows -> {out_path}")

    print(f"\n{'=' * 78}\nRunning audit gate...\n{'=' * 78}")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_csv.py"), str(out_path)]
    )
    if result.returncode != 0:
        print("\nAUDIT FAILED — see findings above. Not safe to load.")
        sys.exit(1)
    print(f"\n{args.entity}: extract + audit both green.")


if __name__ == "__main__":
    main()
