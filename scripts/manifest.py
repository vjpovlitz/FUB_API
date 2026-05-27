"""Write data/exports/manifest.json (row counts + sha256 + schema fingerprint).

    .venv/bin/python scripts/manifest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fub_api.manifest import write_manifest  # noqa: E402

EXPORT_DIR = ROOT / "data" / "exports"


def main() -> None:
    out = write_manifest(EXPORT_DIR)
    data = json.loads(out.read_text(encoding="utf-8"))
    print(f"Wrote {out}")
    for f in data["files"]:
        print(f"  {f['file']:16} rows={f['rows']:>6}  cols={f['columns']:>3}  "
              f"sha256={f['sha256'][:12]}…  {f['size_bytes']:>9,} bytes")


if __name__ == "__main__":
    main()
