"""Manifest writer for load verification.

For every CSV in the export dir, record row count, sha256, byte size, and a
column fingerprint. Post-load, the SQL `COUNT(*)` per table (see
load_bulk_insert.sql) must equal `rows` here — that's the extract<->load
reconciliation. The sha256 lets you prove a file didn't change between
extract and load.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _now_utc_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_entry(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = sum(1 for _ in reader)
    col_fp = hashlib.sha256("|".join(header).encode("utf-8")).hexdigest()
    return {
        "file": path.name,
        "rows": rows,
        "columns": len(header),
        "column_names": header,
        "schema_fingerprint": col_fp,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def build_manifest(export_dir: Path) -> dict:
    csvs = sorted(p for p in export_dir.glob("*.csv"))
    return {
        "generated_at_utc": _now_utc_iso(),
        "source_system": "FollowUpBoss",
        "files": [file_entry(p) for p in csvs],
    }


def write_manifest(export_dir: Path) -> Path:
    manifest = build_manifest(export_dir)
    out = export_dir / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out
