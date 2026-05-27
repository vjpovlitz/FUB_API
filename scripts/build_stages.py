"""Build the unified Stages dimension from two FUB endpoints.

The standalone GET /stages collection returns ONLY person stages (pipelineId=
null). Deal-pipeline stages live exclusively inside GET /pipelines[].stages[],
so a person-only Stages table leaves every Deals.StageId orphaned. This script
unions both into one Stages.csv (disjoint id ranges; StageKind marks the
source), then runs the audit gate.

    .venv/bin/python scripts/build_stages.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fub_api.client import FUBClient  # noqa: E402
from fub_api.mappers import STAGE_COLUMNS, map_stage  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from export import _now_utc_iso, write_csv  # noqa: E402

EXPORT_DIR = ROOT / "data" / "exports"


def _page_all(resource) -> list[dict]:
    rows: list[dict] = []
    next_token: str | None = None
    while True:
        api_rows, next_token = resource.page(limit=100, next_token=next_token)
        if not api_rows:
            break
        rows.extend(api_rows)
        if next_token is None:
            break
    return rows


def main() -> None:
    extracted_at = _now_utc_iso()
    out_rows: list[dict] = []
    seen: set[str] = set()

    with FUBClient.from_env() as client:
        person_stages = _page_all(client.stages)
        pipelines = _page_all(client.pipelines)

    # Person stages first (authoritative for the person-stage ids).
    for s in person_stages:
        sid = str(s.get("id"))
        seen.add(sid)
        out_rows.append(map_stage(s, extracted_at=extracted_at, kind="Person"))

    # Deal stages nested under each pipeline; pipeline_id is the parent's id.
    deal_added = 0
    for p in pipelines:
        for s in p.get("stages") or []:
            sid = str(s.get("id"))
            if sid in seen:
                continue  # disjoint in practice; guard against id reuse
            seen.add(sid)
            out_rows.append(
                map_stage(s, extracted_at=extracted_at, pipeline_id=p.get("id"), kind="Deal")
            )
            deal_added += 1

    out_path = EXPORT_DIR / "Stages.csv"
    write_csv(out_rows, STAGE_COLUMNS, out_path)
    print(f"Person stages: {len(person_stages)}  +  Deal stages: {deal_added}  "
          f"=  {len(out_rows)} rows -> {out_path}")

    print(f"\n{'=' * 78}\nRunning audit gate...\n{'=' * 78}")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_csv.py"), str(out_path)]
    )
    if result.returncode != 0:
        print("\nAUDIT FAILED — see findings above. Not safe to load.")
        sys.exit(1)
    print("\nStages (unified): build + audit both green.")


if __name__ == "__main__":
    main()
