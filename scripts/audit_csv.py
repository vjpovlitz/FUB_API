"""Audit a CSV file for SQL-Server / BULK INSERT data quality issues.

Vendor-agnostic — ported from GHL_API. Reports:
- Embedded newlines inside fields (CR / LF / CRLF)  <-- the silent-row-loss bug
- Tabs inside fields
- NULL bytes / other C0 control characters
- Leading/trailing whitespace
- Non-UTF-8 / invalid bytes / missing BOM
- Long fields that might overflow NVARCHAR sizes
- Empty PK values
- Inconsistent column counts
- Unicode normalization quirks

The core check is physical lines vs logical CSV rows — they must match, or
BULK INSERT will mis-parse embedded newlines.

Usage:
    .venv/bin/python scripts/audit_csv.py [path ...]
    .venv/bin/python scripts/audit_csv.py            # audits all CSVs in data/exports/
"""
from __future__ import annotations

import csv
import sys
import unicodedata
from collections import Counter
from pathlib import Path

EXPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "exports"

PK_COLUMNS = {
    "People.csv": "PersonId",
    "Deals.csv": "DealId",
    "Events.csv": "EventId",
    "Tasks.csv": "TaskId",
    "Notes.csv": "NoteId",
    "Calls.csv": "CallId",
    "Users.csv": "UserId",
    "Pipelines.csv": "PipelineId",
    "Stages.csv": "StageId",
    "Sources.csv": "SourceId",
    "Tags.csv": "TagName",
}

BAD_CONTROL_CODES = set(range(0, 9)) | {11, 12} | set(range(14, 32))


def audit_file(path: Path) -> dict:
    print(f"\n{'=' * 78}")
    print(f"AUDIT: {path}")
    print("=" * 78)

    raw = path.read_bytes()
    findings: dict[str, list] = {"byte_level": []}

    # ---- byte-level ----
    if not raw.startswith(b"\xef\xbb\xbf"):
        findings["byte_level"].append("missing UTF-8 BOM (rule 5)")
    if b"\x00" in raw:
        findings["byte_level"].append(f"contains {raw.count(b'\\x00')} NULL bytes")
    try:
        raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        findings["byte_level"].append(f"invalid UTF-8: {e}")

    lf_only = raw.count(b"\n") - raw.count(b"\r\n")
    crlf = raw.count(b"\r\n")
    findings["byte_level"].append(f"line endings: CRLF={crlf}, bare-LF={lf_only}")

    # ---- row/field level via csv (proper file-mode parse) ----
    physical_lines = raw.count(b"\n")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        expected_cols = len(header)
        logical_rows = list(reader)

    print(f"  Physical lines (BULK INSERT view): {physical_lines}")
    print(f"  Logical CSV rows (data + header):  {len(logical_rows) + 1}")
    if physical_lines > len(logical_rows) + 1:
        diff = physical_lines - (len(logical_rows) + 1)
        findings["byte_level"].append(
            f"{diff} embedded newlines mid-field — BULK INSERT will mis-parse"
        )

    pk_col = PK_COLUMNS.get(path.name)
    pk_idx = header.index(pk_col) if pk_col and pk_col in header else None

    bad_col_counts: list[tuple[int, int]] = []
    empty_pks: list[int] = []
    field_issues: Counter[str] = Counter()
    long_fields_top: list[tuple[int, str, int]] = []

    data_rows = 0
    for i, row in enumerate(logical_rows, start=2):
        data_rows += 1
        if len(row) != expected_cols:
            bad_col_counts.append((i, len(row)))
        for j, val in enumerate(row):
            col = header[j] if j < len(header) else f"col{j}"
            if pk_idx is not None and j == pk_idx and not val:
                empty_pks.append(i)
            if "\n" in val or "\r" in val:
                field_issues[f"embedded newline in {col}"] += 1
            if "\t" in val:
                field_issues[f"embedded tab in {col}"] += 1
            if any(ord(c) in BAD_CONTROL_CODES for c in val):
                field_issues[f"control char in {col}"] += 1
            if val != val.strip():
                field_issues[f"untrimmed whitespace in {col}"] += 1
            if unicodedata.normalize("NFC", val) != val:
                field_issues[f"non-NFC unicode in {col}"] += 1
            if len(val) > 1000:
                long_fields_top.append((i, col, len(val)))

    # ---- report ----
    print(f"\nHeader columns: {expected_cols}")
    print(f"Data rows:      {data_rows}")

    print("\n[byte-level]")
    for f in findings["byte_level"]:
        print(f"  - {f}")

    print("\n[row-level]")
    if bad_col_counts:
        print(f"  - {len(bad_col_counts)} rows with wrong column count")
        for r, n in bad_col_counts[:5]:
            print(f"      line {r}: {n} cols (expected {expected_cols})")
    else:
        print("  - all rows have correct column count  OK")
    if empty_pks:
        print(f"  - {len(empty_pks)} rows with empty PK ({pk_col})")
    elif pk_col:
        print("  - no empty PK values  OK")

    print("\n[field-level]")
    if field_issues:
        for issue, n in field_issues.most_common():
            print(f"  - {n:>5}  {issue}")
    else:
        print("  - no field-level issues  OK")

    print("\n[long fields > 1000 chars]")
    if long_fields_top:
        long_fields_top.sort(key=lambda x: -x[2])
        for r, col, ln in long_fields_top[:5]:
            print(f"  - line {r}  col={col}  len={ln}")
    else:
        print("  - none")

    embedded_nl = sum(1 for f in findings["byte_level"] if "embedded newlines" in f)
    return {
        "path": str(path),
        "field_issues": dict(field_issues),
        "bad_rows": len(bad_col_counts),
        "empty_pks": len(empty_pks),
        "embedded_newlines": embedded_nl,
    }


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] or sorted(EXPORT_DIR.glob("*.csv"))
    if not paths:
        print("No CSVs to audit.")
        sys.exit(1)
    summaries = [audit_file(p) for p in paths]
    print(f"\n{'=' * 78}\nOVERALL\n{'=' * 78}")
    total_issues = (
        sum(sum(s["field_issues"].values()) for s in summaries)
        + sum(s["bad_rows"] for s in summaries)
        + sum(s["empty_pks"] for s in summaries)
        + sum(s["embedded_newlines"] for s in summaries)
    )
    print(f"Files audited: {len(summaries)}")
    print(f"Total issues : {total_issues}")
    if total_issues > 0:
        print("\nFIX NEEDED before SQL Server load.")
        sys.exit(1)
    print("\nAll clear — safe to load.")


if __name__ == "__main__":
    main()
