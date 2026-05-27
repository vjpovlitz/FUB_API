"""Derive the Sources and Tags dimensions from an already-extracted People.csv.

FUB exposes no usable endpoint for either on the current key (/sources 404,
/leadSources 403, /tags 403 — non-owner scope), so these dims are built by
distinct-ing the People fact:

    Sources <- distinct (SourceId, Source), with a per-source people count
    Tags    <- distinct pipe-delimited Tags values, with a per-tag people count

Both rows carry Derived="1" so they can be re-pulled authoritatively once an
owner-scoped key is registered (then swap them for a live extract). Writes
SQL-Server-shaped CSVs (BOM/CRLF/QUOTE_MINIMAL via export.write_csv) and runs
the audit gate, exiting non-zero on any finding.

    .venv/bin/python scripts/derive_dims.py
"""
from __future__ import annotations

import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fub_api.mappers import (  # noqa: E402
    SOURCE_COLUMNS,
    TAG_COLUMNS,
    map_source,
    map_tag,
)

# write_csv + the UTC timestamp helper already enforce DATA_RULES formatting.
sys.path.insert(0, str(ROOT / "scripts"))
from export import _now_utc_iso, write_csv  # noqa: E402

EXPORT_DIR = ROOT / "data" / "exports"
PEOPLE_CSV = EXPORT_DIR / "People.csv"


def _read_people() -> list[dict]:
    if not PEOPLE_CSV.exists():
        print(f"ERROR: {PEOPLE_CSV} not found — extract People first "
              f"(scripts/export.py --entity people).")
        sys.exit(1)
    with PEOPLE_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def derive_sources(people: list[dict]) -> list[dict]:
    # Count by SourceId; remember the name seen for each id. Skip rows with no
    # SourceId (can't key a source row without one — the name still lives on the
    # person and in any future live pull).
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for p in people:
        sid = (p.get("SourceId") or "").strip()
        if not sid:
            continue
        counts[sid] += 1
        name = (p.get("Source") or "").strip()
        if name:
            names.setdefault(sid, name)
    recs = [
        {"source_id": sid, "name": names.get(sid, ""), "people_count": n}
        for sid, n in counts.items()
    ]
    recs.sort(key=lambda r: int(r["source_id"]))
    return recs


def derive_tags(people: list[dict]) -> list[dict]:
    # People.Tags is pipe-delimited; one person can carry several tags.
    counts: Counter[str] = Counter()
    for p in people:
        for tag in (p.get("Tags") or "").split("|"):
            tag = tag.strip()
            if tag:
                counts[tag] += 1
    recs = [{"name": name, "people_count": n} for name, n in counts.items()]
    recs.sort(key=lambda r: (-r["people_count"], r["name"]))
    return recs


def main() -> None:
    people = _read_people()
    extracted_at = _now_utc_iso()
    print(f"Read {len(people)} People rows from {PEOPLE_CSV.name}")

    jobs = [
        ("Sources", SOURCE_COLUMNS, map_source, derive_sources(people), "Sources.csv"),
        ("Tags", TAG_COLUMNS, map_tag, derive_tags(people), "Tags.csv"),
    ]

    out_paths: list[Path] = []
    for label, columns, mapper, recs, filename in jobs:
        rows = [mapper(r, extracted_at=extracted_at) for r in recs]
        out_path = EXPORT_DIR / filename
        write_csv(rows, columns, out_path)
        out_paths.append(out_path)
        print(f"  {label}: {len(rows)} rows -> {out_path}")

    print(f"\n{'=' * 78}\nRunning audit gate...\n{'=' * 78}")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_csv.py"), *map(str, out_paths)]
    )
    if result.returncode != 0:
        print("\nAUDIT FAILED — see findings above. Not safe to load.")
        sys.exit(1)
    print("\nSources + Tags: derive + audit both green.")


if __name__ == "__main__":
    main()
