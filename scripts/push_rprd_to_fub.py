"""Production RPRD -> FUB push (idempotent, scored distressed-seller leads).

Reads the RPRD lead engine's `lead_score.csv` (one ranked row per parcel) and
upserts each into FUB via `fub_api.pusher.FubPusher`. Keyed on `rprd:<parcel_id>`
so the 3x/day cadence skips unchanged leads, updates re-scored ones, and creates
only new parcels. Each lead is tagged by its signal(s) — probate / foreclosure /
tax-lien — plus the umbrella `niche⚡️ auto-import` tag for one-filter cleanup.

lead_score.csv path: $RPRD_LEAD_SCORE, else the CoWork warehouse default.

  python scripts/push_rprd_to_fub.py             # dry-run, all leads
  python scripts/push_rprd_to_fub.py --push      # live upsert
  python scripts/push_rprd_to_fub.py --push -n 2 # live, top 2 (smoke)
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fub_api import FUBClient  # noqa: E402
from fub_api.pusher import FubPusher, Ledger, signal_tag, split_owner_name  # noqa: E402

RPRD_SOURCE = "RPRD Lead Engine"
DEFAULT_LEAD_SCORE = Path(
    os.getenv("RPRD_LEAD_SCORE")
    or r"C:\Users\vjpov\Codebase\DCR\Claude CoWork Project\RPRD-Leads\RPRD-Leads\warehouse\lead_score.csv"
)


def _state(jurisdiction: str) -> str:
    return "DC" if "DC" in (jurisdiction or "").upper() or "WASHINGTON" in (jurisdiction or "").upper() else "MD"


def _is_absentee(flag: str) -> bool:
    return (flag or "").strip().upper() in ("", "N", "0")


def _addr_key(addr: str) -> str:
    """Street comparison key: drop a trailing zip+4 suffix and non-alnum noise."""
    base = re.sub(r"-\d{4}\b", "", addr or "").upper()
    return re.sub(r"[^A-Z0-9]", "", base)


def build(row: dict) -> tuple[str, dict, list[str], dict | None, list[dict]]:
    """lead_score.csv row -> (external_id, person_body, signal_tags, note, [])."""
    parcel_id = (row.get("parcel_id") or "").strip()
    external_id = f"rprd:{parcel_id}"
    juris = row.get("jurisdiction") or ""
    state = _state(juris)

    first, last = split_owner_name(row.get("owner_name"))
    body: dict = {"lastName": last}
    if first:
        body["firstName"] = first
    addresses: list[dict] = []
    situs = (row.get("situs_address") or "").strip()
    if situs:
        addresses.append({"type": "property", "street": situs, "state": state})
    mailing = (row.get("owner_mailing_address") or "").strip()
    if mailing and _addr_key(mailing) != _addr_key(situs):
        addresses.append({"type": "mailing", "street": mailing})
    if addresses:
        body["addresses"] = addresses
    body["customOccupancy"] = "Absentee" if _is_absentee(row.get("owner_occupied_flag")) else "Owner Occupied"

    signals = [s for s in (row.get("signals") or "").split(";") if s.strip()]
    tags = sorted({t for s in signals if (t := signal_tag(s))})

    note = {
        "subject": f"RPRD lead score {row.get('score')} ({row.get('signals')})",
        "body": "\n".join([
            f"Score:        {row.get('score')}  (signals: {row.get('signals')}, count {row.get('signal_count')})",
            f"Jurisdiction: {juris}",
            f"Property:     {situs}",
            f"Owner:        {row.get('owner_name')}",
            f"Mailing:      {mailing or 'n/a'}",
            f"Assessed:     {row.get('assessed_value') or 'n/a'}",
            f"Match:        {row.get('match_confidence')}",
            f"Details:      {row.get('details')}",
            f"Parcel id:    {parcel_id}",
        ]),
        "isHtml": False,
    }
    return external_id, body, tags, note, []


def push(pusher: FubPusher, lead_score: Path, *, limit: int | None, now: str) -> None:
    if not lead_score.exists():
        pusher.log(f"! lead_score.csv not found at {lead_score} — skipping RPRD push")
        return
    n = 0
    with lead_score.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):  # already sorted by score desc
            external_id, body, tags, note, rels = build(row)
            pusher.upsert(external_id, body, tags, note=note, relationships=rels, now=now)
            n += 1
            if limit is not None and n >= limit:
                break
            if n % 500 == 0:
                pusher.log(f"  ...rprd {n} processed ({pusher.stats})")
    pusher.log(f"RPRD push done: {n} leads -> {pusher.stats}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="live upsert (default dry-run)")
    ap.add_argument("-n", "--limit", type=int, default=None, help="cap records (smoke test)")
    ap.add_argument("--lead-score", type=Path, default=DEFAULT_LEAD_SCORE, help="path to lead_score.csv")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    ledger = Ledger()
    fub = FUBClient.from_env() if args.push else None
    pusher = FubPusher(fub, ledger, source=RPRD_SOURCE, dry_run=not args.push)
    print(f"=== RPRD -> FUB ({'LIVE' if args.push else 'DRY-RUN'}) source={RPRD_SOURCE!r} src={args.lead_score} ===")
    push(pusher, args.lead_score, limit=args.limit, now=now)
    if pusher.stats.failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
