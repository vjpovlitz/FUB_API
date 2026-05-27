"""Referential-integrity gate for the exported CSVs.

Asserts every foreign key in a fact CSV resolves to a primary key in its
dimension/fact CSV BEFORE the SQL Server load — catching orphans that would
otherwise become NULLs (or violate FKs) in the warehouse. Mirrors the audit
gate: prints a per-relationship report and exits non-zero on any orphan.

Empty FK values are skipped (the columns are nullable — a person with no
Source isn't an orphan). Multi-valued columns (pipe-delimited: Tags, PersonIds,
UserIds) are split and each value checked.

    .venv/bin/python scripts/check_integrity.py
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

EXPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "exports"


@dataclass(frozen=True)
class Rule:
    fact_file: str
    fact_col: str
    dim_file: str
    dim_col: str
    multi: bool = False  # fact_col is pipe-delimited


# Every FK we expect to resolve. AssignedLenderId/AssignedPondId/LeadFlowId are
# omitted: no dimension exists for them and they're empty in this account.
RULES = [
    Rule("People.csv", "StageId", "Stages.csv", "StageId"),
    Rule("People.csv", "SourceId", "Sources.csv", "SourceId"),
    Rule("People.csv", "AssignedUserId", "Users.csv", "UserId"),
    Rule("People.csv", "Tags", "Tags.csv", "TagName", multi=True),
    Rule("Deals.csv", "PipelineId", "Pipelines.csv", "PipelineId"),
    Rule("Deals.csv", "StageId", "Stages.csv", "StageId"),
    Rule("Deals.csv", "PrimaryPersonId", "People.csv", "PersonId"),
    Rule("Deals.csv", "PersonIds", "People.csv", "PersonId", multi=True),
    Rule("Deals.csv", "PrimaryUserId", "Users.csv", "UserId"),
    Rule("Deals.csv", "UserIds", "Users.csv", "UserId", multi=True),
    Rule("Events.csv", "PersonId", "People.csv", "PersonId"),
]


def _load(name: str, _cache: dict[str, list[dict]] = {}) -> list[dict]:
    if name not in _cache:
        path = EXPORT_DIR / name
        if not path.exists():
            _cache[name] = []
        else:
            with path.open(encoding="utf-8-sig", newline="") as f:
                _cache[name] = list(csv.DictReader(f))
    return _cache[name]


def _fact_values(rows: list[dict], col: str, multi: bool) -> set[str]:
    out: set[str] = set()
    for r in rows:
        raw = r.get(col) or ""
        parts = raw.split("|") if multi else [raw]
        for p in parts:
            p = p.strip()
            if p:
                out.add(p)
    return out


def _dim_keys(rows: list[dict], col: str) -> set[str]:
    return {(r.get(col) or "").strip() for r in rows if (r.get(col) or "").strip()}


def main() -> None:
    print(f"{'=' * 78}\nREFERENTIAL INTEGRITY\n{'=' * 78}")
    missing_files: set[str] = set()
    total_orphans = 0

    for rule in RULES:
        label = f"{rule.fact_file[:-4]}.{rule.fact_col} -> {rule.dim_file[:-4]}.{rule.dim_col}"
        fact_rows = _load(rule.fact_file)
        dim_rows = _load(rule.dim_file)

        if not (EXPORT_DIR / rule.fact_file).exists():
            missing_files.add(rule.fact_file)
            print(f"  SKIP  {label}  (missing {rule.fact_file})")
            continue
        if not (EXPORT_DIR / rule.dim_file).exists():
            missing_files.add(rule.dim_file)
            print(f"  SKIP  {label}  (missing {rule.dim_file})")
            continue

        fact_vals = _fact_values(fact_rows, rule.fact_col, rule.multi)
        dim_keys = _dim_keys(dim_rows, rule.dim_col)
        orphans = sorted(fact_vals - dim_keys)
        resolved = len(fact_vals) - len(orphans)

        status = "OK" if not orphans else f"{len(orphans)} ORPHANS"
        print(f"  {label:<46} {resolved:>5}/{len(fact_vals):<5} resolve  {status}")
        if orphans:
            total_orphans += len(orphans)
            print(f"        sample orphan {rule.fact_col} values: {orphans[:10]}")

    print(f"\n{'=' * 78}\nOVERALL\n{'=' * 78}")
    print(f"Rules checked : {len(RULES)}")
    print(f"Total orphans : {total_orphans}")
    if missing_files:
        print(f"Missing CSVs  : {sorted(missing_files)}  (run the relevant extract first)")

    if total_orphans or missing_files:
        print("\nINTEGRITY FAILED — resolve orphans / missing files before SQL load.")
        sys.exit(1)
    print("\nAll foreign keys resolve — safe to load.")


if __name__ == "__main__":
    main()
