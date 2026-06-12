"""Target scope for the Niche -> warehouse -> FUB pipeline.

v1 scope (per founder): foreclosures + pre-foreclosures (lis-pendens/NOD) +
pre-probate, across the DC/Baltimore metro counties below.

VERIFIED against live data 2026-06-04 (scripts/niche_smoke.py):
  - The `type` filter WORKS (slug-based, case-insensitive; CSV = OR). Currently
    the entire dataset is `foreclosures` (5,705); `lis-pendens-or-nod` and
    `pre-probate` both return 0 — they're kept so we auto-pick them up the day
    Niche starts populating them for this account.
  - `state`/`county` filters WORK. The whole dataset is Maryland; DC = 0.
  - `county` strings come back UPPERCASE with NO apostrophe (e.g. "PRINCE
    GEORGES"). The filter is case-insensitive but we store Niche's exact strings.
  - Page size is FIXED at 15 server-side (`itemsPerPage` is ignored); the
    paginator walks `links.next` (JSON:API), so this only affects request count.
"""
from __future__ import annotations

from dataclasses import dataclass

# Niche record-type slugs to pull (see docs: Slug <-> Label table).
TARGET_TYPES: list[str] = ["foreclosures", "lis-pendens-or-nod", "pre-probate"]

# Comma-joined for the `type=` query param (matching is case-insensitive).
TYPE_PARAM: str = ",".join(TARGET_TYPES)


@dataclass(frozen=True)
class County:
    label: str          # human label
    state: str          # Niche `state` code
    county: str | None  # Niche `county` exact match (None -> filter by state only)


# VERIFIED 2026-06-04 — counts sum to the full 5,705 (all foreclosures, all MD).
# Strings are Niche's exact `county` spelling (UPPERCASE, no apostrophe).
TARGET_COUNTIES: list[County] = [
    County("Baltimore City",  "MD", "BALTIMORE CITY"),   # 2,181 — independent city
    County("Prince George's", "MD", "PRINCE GEORGES"),   # 1,910 — no apostrophe in Niche
    County("Baltimore County","MD", "BALTIMORE"),        #   990 — distinct from the city
    County("Anne Arundel",    "MD", "ANNE ARUNDEL"),     #   624
    # Washington DC: 0 records for this account today; add back if DC data lands.
]
