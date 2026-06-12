"""Niche Data smoke test + schema/county discovery.

Run this FIRST (with your token in .env as NICHE_DATA_TOKEN). It:
  1. Verifies auth + connectivity (counts per target type).
  2. Discovers the EXACT state/county strings present (county is an exact-match
     filter, so we need Niche's spelling — see config.TARGET_COUNTIES).
  3. Detects the response envelope (Hydra vs plain) + a notice's field keys.
  4. Writes a raw sample to data/exports/niche_sample_raw.json (gitignored) for
     designing the warehouse mapper — NOT printed, since it may contain PII.

Usage:
    python scripts/niche_smoke.py
    python scripts/niche_smoke.py --state MD --sample 50
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from niche_api import NicheClient  # noqa: E402
from niche_api.config import TARGET_TYPES, TYPE_PARAM  # noqa: E402
from niche_api.resources import _base  # noqa: E402

OUT = REPO_ROOT / "data" / "exports" / "niche_sample_raw.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=None, help="limit discovery to one state code (e.g. MD)")
    ap.add_argument("--sample", type=int, default=50, help="records to scan for state/county discovery")
    args = ap.parse_args()

    try:
        client = NicheClient.from_env()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL connect: {e}")
        return 1

    print("=" * 70)
    print("Niche Data smoke test")
    print(f"  base: {client.base_url}")
    print(f"  types: {TYPE_PARAM}")
    print("=" * 70)

    # 1. Per-type counts (also the auth check).
    scope = f" (state={args.state})" if args.state else ""
    print(f"\n[1] Counts per target type{scope}")
    for t in TARGET_TYPES:
        try:
            n = client.notices.count(type=t, state=args.state)
            print(f"    {t:22} {n if n is not None else '?':>10}")
        except Exception as e:  # noqa: BLE001
            print(f"    {t:22} ERROR: {e}")
            return 1

    # 2/3. Pull a sample, detect envelope, collect field keys + distinct geos.
    print(f"\n[2] Scanning up to {args.sample} records for envelope + geography...")
    raw_resp = client.notices.list(page=1, items_per_page=min(args.sample, 50),
                                   type=TYPE_PARAM, state=args.state)
    envelope_keys = sorted(raw_resp.keys()) if isinstance(raw_resp, dict) else ["<list>"]
    print(f"    envelope keys: {envelope_keys}")
    print(f"    totalItems:    {_base.total_items(raw_resp)}")
    print(f"    next link:     {_base.next_path(raw_resp)}")

    records = list(client.notices.iterate(type=TYPE_PARAM, state=args.state,
                                          max_records=args.sample, items_per_page=50))
    print(f"    pulled {len(records)} sample records")
    if not records:
        print("    (no records — check token scope / filters)")
        return 2

    field_keys = sorted({k for r in records for k in r.keys()})
    print(f"\n[3] Notice field keys ({len(field_keys)}):")
    for k in field_keys:
        print(f"      - {k}")

    def vals(field: str) -> Counter:
        return Counter(str(r.get(field, "")).strip() for r in records if r.get(field) not in (None, ""))

    print("\n[4] Distinct STATE values:")
    for v, c in vals("state").most_common():
        print(f"      {v!r}: {c}")
    print("\n[5] Distinct COUNTY values (use these EXACT strings in config):")
    county_field = next((f for f in ("county", "countyName", "county_name") if f in field_keys), "county")
    for v, c in Counter(str(r.get(county_field, "")).strip() for r in records if r.get(county_field)).most_common():
        print(f"      {v!r}: {c}")
    print("\n[6] Distinct TYPE values:")
    type_field = next((f for f in ("type", "recordType", "typeLabel", "typeSlug") if f in field_keys), "type")
    for v, c in Counter(str(r.get(type_field, "")).strip() for r in records if r.get(type_field)).most_common():
        print(f"      {v!r}: {c}")

    # 4. Dump raw sample for offline mapper design (gitignored).
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"envelope_keys": envelope_keys, "sample": records[:10]},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote raw sample (first 10) -> {OUT.relative_to(REPO_ROOT)} (gitignored)")
    print("Share the [1]-[6] summary above; I'll finalize the mapper from the raw file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
