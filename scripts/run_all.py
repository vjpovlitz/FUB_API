"""Full-refresh orchestrator: extract everything, validate, manifest — one
command, one exit code.

Runs the existing scripts in dependency order (each enforces its own audit
gate; we stop at the first non-zero exit):

    1. People / Deals / Events / Users / Pipelines   (scripts/export.py)
    2. Stages   = /stages ∪ /pipelines[].stages[]     (scripts/build_stages.py)
    3. Sources + Tags  (derived from People.csv)       (scripts/derive_dims.py)
    4. Referential-integrity gate                      (scripts/check_integrity.py)
    5. Manifest (row counts + sha256)                  (scripts/manifest.py)

Order matters: People must land before derive_dims (it reads People.csv), and
every CSV must exist before the integrity gate. On success the warehouse load
inputs in data/exports/ are complete + internally consistent.

    .venv/bin/python scripts/run_all.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PY = sys.executable


def _export(entity: str) -> list[str]:
    return [PY, str(SCRIPTS / "export.py"), "--entity", entity]


# (label, argv) in dependency order.
STEPS: list[tuple[str, list[str]]] = [
    ("People", _export("people")),
    ("Deals", _export("deals")),
    ("Events", _export("events")),
    ("Tasks", _export("tasks")),
    ("Notes", _export("notes")),
    ("Calls", _export("calls")),
    ("Users", _export("users")),
    ("Pipelines", _export("pipelines")),
    ("Stages (unified)", [PY, str(SCRIPTS / "build_stages.py")]),
    ("Sources + Tags", [PY, str(SCRIPTS / "derive_dims.py")]),
    ("Integrity gate", [PY, str(SCRIPTS / "check_integrity.py")]),
    ("Manifest", [PY, str(SCRIPTS / "manifest.py")]),
]


def main() -> None:
    started = time.monotonic()
    timings: list[tuple[str, float]] = []

    for i, (label, argv) in enumerate(STEPS, start=1):
        print(f"\n{'#' * 78}\n# [{i}/{len(STEPS)}] {label}\n{'#' * 78}")
        t0 = time.monotonic()
        result = subprocess.run(argv)
        dt = time.monotonic() - t0
        timings.append((label, dt))
        if result.returncode != 0:
            print(f"\n>>> STEP FAILED: {label} (exit {result.returncode}). "
                  f"Stopping — data/exports/ is NOT load-ready.")
            sys.exit(1)

    total = time.monotonic() - started
    print(f"\n{'=' * 78}\nFULL REFRESH COMPLETE\n{'=' * 78}")
    for label, dt in timings:
        print(f"  {label:<22} {dt:7.1f}s")
    print(f"  {'TOTAL':<22} {total:7.1f}s")
    print("\nAll extracts + audit gates + integrity check passed. "
          "data/exports/ is ready for the SQL Server load (see sql/).")


if __name__ == "__main__":
    main()
