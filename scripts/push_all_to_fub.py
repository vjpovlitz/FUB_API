"""Combined FUB push: Niche foreclosures + RPRD scored leads, one exit code.

This is the entry point the scheduled "FUB Niche Push" task runs at 9:00 / 15:00
/ 21:00 (30 min after the RPRD lead scrape at 8:30 / 14:30 / 20:30). Both feeds
share ONE ledger (external ids are namespaced `niche:` / `rprd:`), so dedup is
global and a lead is never double-created across feeds.

  python scripts/push_all_to_fub.py             # dry-run both feeds
  python scripts/push_all_to_fub.py --push      # live upsert both
  python scripts/push_all_to_fub.py --push --only niche
  python scripts/push_all_to_fub.py --push -n 2 # live smoke (2 per feed)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fub_api import FUBClient  # noqa: E402
from fub_api.pusher import FubPusher, Ledger  # noqa: E402
from niche_api import NicheClient  # noqa: E402
import push_niche_to_fub as niche_push  # noqa: E402
import push_rprd_to_fub as rprd_push  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="live upsert (default dry-run)")
    ap.add_argument("-n", "--limit", type=int, default=None, help="cap records per feed (smoke test)")
    ap.add_argument("--only", choices=["niche", "rprd"], help="run only one feed")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    mode = "LIVE" if args.push else "DRY-RUN"
    print(f"########## FUB PUSH ({mode}) @ {now} ##########")

    ledger = Ledger()
    fub = FUBClient.from_env() if args.push else None
    rc = 0

    if args.only != "rprd":
        niche = NicheClient.from_env()
        p = FubPusher(fub, ledger, source=niche_push.NICHE_SOURCE, dry_run=not args.push)
        print(f"\n--- Niche -> FUB (source={niche_push.NICHE_SOURCE!r}) ---")
        niche_push.push(p, niche, limit=args.limit, now=now)
        rc = rc or (1 if p.stats.failures else 0)

    if args.only != "niche":
        p = FubPusher(fub, ledger, source=rprd_push.RPRD_SOURCE, dry_run=not args.push)
        print(f"\n--- RPRD -> FUB (source={rprd_push.RPRD_SOURCE!r}) ---")
        rprd_push.push(p, rprd_push.DEFAULT_LEAD_SCORE, limit=args.limit, now=now)
        rc = rc or (1 if p.stats.failures else 0)

    print(f"\n########## FUB PUSH complete (exit {rc}) ##########")
    return rc


if __name__ == "__main__":
    sys.exit(main())
