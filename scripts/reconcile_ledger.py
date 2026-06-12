"""Reconcile the push ledger against FUB reality (founder bulk-deletes, 2026-06-10).

The ledger (`data/exports/push_ledger.jsonl`) maps external ids -> FUB person
ids. When leads are bulk-deleted inside FUB (founder deleted all 10,217 RPRD
leads and 5,756 old Niche leads on 2026-06-10), those entries go stale: the
pusher would "skip" leads that no longer exist or PUT updates at deleted ids.

This script pages every person id actually in FUB (incl. Trash) and rewrites
the ledger keeping only entries whose person still exists. The old ledger is
backed up alongside (`.bak-<stamp>`); the rewrite is atomic (tmp + os.replace).

NOTE: run this only AFTER the push filters match what should be re-created —
a purged entry means the next push POSTs that lead again if its feed row still
passes the filters.

  python scripts/reconcile_ledger.py            # report only (dry-run)
  python scripts/reconcile_ledger.py --write    # backup + rewrite the ledger
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fub_api import FUBClient  # noqa: E402
from fub_api.pusher import DEFAULT_LEDGER  # noqa: E402


def fetch_existing_ids(fub: FUBClient) -> set[str]:
    """Every person id currently in FUB, including Trash."""
    ids: set[str] = set()
    params = {"limit": 100, "fields": "id", "includeTrash": "true"}
    resp = fub.request("GET", "/people", params=params)
    while True:
        people = resp.get("people") or []
        if not people:
            break
        ids.update(str(p["id"]) for p in people if p.get("id") is not None)
        nxt = (resp.get("_metadata") or {}).get("next")
        if not nxt:
            break
        resp = fub.request("GET", "/people", params={**params, "next": nxt})
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="rewrite the ledger (default: report only)")
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = ap.parse_args()

    if not args.ledger.exists():
        print(f"no ledger at {args.ledger} — nothing to do")
        return 0

    # Last-wins per external id, same as pusher.Ledger.
    entries: dict[str, dict] = {}
    with args.ledger.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("external_id"):
                entries[rec["external_id"]] = rec

    print(f"ledger: {len(entries)} unique external ids")
    print("fetching existing FUB person ids (incl. Trash)...")
    existing = fetch_existing_ids(FUBClient.from_env())
    print(f"FUB currently has {len(existing)} people")

    kept: list[dict] = []
    dropped = Counter()
    kept_ns = Counter()
    for ext, rec in entries.items():
        ns = ext.split(":", 1)[0]
        if str(rec.get("fub_id")) in existing:
            kept.append(rec)
            kept_ns[ns] += 1
        else:
            dropped[ns] += 1

    print(f"\nkeep  {len(kept)}: {dict(kept_ns)}")
    print(f"drop  {sum(dropped.values())}: {dict(dropped)}")

    if not args.write:
        print("\n(report only — rerun with --write to apply)")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = args.ledger.with_suffix(f".jsonl.bak-{stamp}")
    backup.write_bytes(args.ledger.read_bytes())
    tmp = args.ledger.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for rec in kept:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.replace(tmp, args.ledger)
    print(f"\nrewrote {args.ledger} ({len(kept)} entries); backup at {backup.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
