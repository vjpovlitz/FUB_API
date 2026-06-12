"""Export RPRD leads as a DataSift-ready skip-trace CSV (founder workflow, 2026-06-10).

RPRD leads carry no phone numbers, so they must be skip-traced (DataSift) before
any FUB import. This script replaces the old direct RPRD->FUB push: it reads the
RPRD lead engine's ``lead_score.csv``, filters to the signals worth paying to
trace (default: probate + preforeclosure — tax-lien-only rows are excluded; they
were 9.8k of the 10.2k leads the founder deleted), enriches probate rows with
the estate record (decedent name, filing/death dates, status, current owner),
and writes a CSV shaped for DataSift's uploader (name + mailing + property
address split into street/city/state/zip, APN fallback).

Exported parcels are recorded in ``data/exports/skiptrace_ledger.jsonl`` so the
scheduled 3x/day run emits ONLY new leads (delta batches). No file is written
when there is nothing new. Re-export everything with --all.

  python scripts/export_skiptrace_csv.py                  # delta, probate+preforeclosure
  python scripts/export_skiptrace_csv.py --all            # ignore ledger, full export
  python scripts/export_skiptrace_csv.py --signals probate
  python scripts/export_skiptrace_csv.py --include-taxlien --min-score 60
  python scripts/export_skiptrace_csv.py --dry-run        # count + preview, write nothing
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fub_api.pusher import split_owner_name  # noqa: E402
from fub_api.sanitize import clean_text  # noqa: E402

RPRD_WAREHOUSE = Path(
    os.getenv("RPRD_WAREHOUSE")
    or r"C:\Users\vjpov\Codebase\DCR\Claude CoWork Project\RPRD-Leads\RPRD-Leads\warehouse"
)
DEFAULT_LEAD_SCORE = Path(os.getenv("RPRD_LEAD_SCORE") or RPRD_WAREHOUSE / "lead_score.csv")
PROBATE_FACTS = RPRD_WAREHOUSE / "fact_probate_howard.csv"
PROBATE_MATCHES = RPRD_WAREHOUSE / "probate_property_matches.csv"

OUT_DIR = REPO_ROOT / "data" / "exports" / "skiptrace"
LEDGER = REPO_ROOT / "data" / "exports" / "skiptrace_ledger.jsonl"

# DataSift maps columns at upload time; extra context columns are harmless.
COLUMNS = [
    "FirstName", "LastName",
    "MailingStreet", "MailingCity", "MailingState", "MailingZip",
    "PropertyStreet", "PropertyCity", "PropertyState", "PropertyZip",
    "APN", "Jurisdiction", "Score", "Signals",
    "EstateNo", "DecedentName", "EstateStatus", "FilingDate", "DateOfDeath",
    "PersonalRep", "CurrentOwner", "OwnershipFlag", "Details",
]

_SUFFIXES = {
    "ST", "AVE", "AV", "RD", "DR", "CT", "LN", "PL", "WAY", "TER", "TERR",
    "BLVD", "CIR", "PKWY", "HWY", "SQ", "RUN", "PIKE", "ROW", "WALK", "PATH",
    "TRL", "LOOP", "BND", "XING", "MEWS", "ALY", "GRN", "PT",
}
_DIRECTIONALS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}
_ESTATE_RE = re.compile(r"estate\s+([A-Z]+-\d+)\s+(.+?)\s*\((OPEN|CLOSED)", re.IGNORECASE)


def split_address(raw: str, default_state: str) -> tuple[str, str, str, str]:
    """Best-effort '1035 48TH ST NE WASHINGTON DC 20019' -> (street, city, state, zip).

    Finds the LAST street-suffix token (plus trailing directional/unit) and cuts
    there; whatever follows is the city. Unsplittable input lands whole in
    street so DataSift still gets the address.
    """
    raw = " ".join((raw or "").replace(",", " ").split())
    if not raw:
        return "", "", "", ""
    zipc = ""
    m = re.search(r"\b(\d{5})(?:-\d{4})?$", raw)
    if m:
        zipc = m.group(1)
        raw = raw[: m.start()].strip()
    state = default_state
    parts = raw.split()
    if parts and parts[-1].upper() in ("MD", "DC", "VA", "WV", "PA", "DE"):
        state = parts[-1].upper()
        parts = parts[:-1]
    cut = None
    for i, tok in enumerate(parts):
        t = tok.upper().rstrip(".,")
        if t in _SUFFIXES and i > 0:
            cut = i
            if i + 1 < len(parts) and parts[i + 1].upper().rstrip(".,") in _DIRECTIONALS:
                cut = i + 1
    if cut is None or cut == len(parts) - 1:
        return " ".join(parts), "", state, zipc
    return " ".join(parts[: cut + 1]), " ".join(parts[cut + 1:]), state, zipc


def load_probate() -> tuple[dict, dict]:
    """estate_no -> fact row; parcel_id -> match row (current owner of record)."""
    facts: dict[str, dict] = {}
    matches: dict[str, dict] = {}
    if PROBATE_FACTS.exists():
        with PROBATE_FACTS.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                facts[(row.get("estate_no") or "").strip()] = row
    if PROBATE_MATCHES.exists():
        with PROBATE_MATCHES.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pid = (row.get("parcel_id") or "").strip()
                if pid:
                    matches[pid] = row
    return facts, matches


def load_backbone(parcel_ids: set[str]) -> dict[str, dict]:
    """Look up MD leads in the SDAT parcel backbone (city/zip/owner/mailing/
    last_sale_date). Uses the small Howard-only extract when every needed
    parcel is HOWA; otherwise streams the full 1.18M-row MD file (~30s)."""
    need = {p for p in parcel_ids if p.startswith("MD-")}
    if not need:
        return {}
    path = RPRD_WAREHOUSE / "dim_parcel_md.csv"
    if all(p.startswith("MD-HOWA-") for p in need) and (RPRD_WAREHOUSE / "dim_parcel_md_howard.csv").exists():
        path = RPRD_WAREHOUSE / "dim_parcel_md_howard.csv"
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = row.get("parcel_id") or ""
            if pid in need:
                out[pid] = row
                if len(out) == len(need):
                    break
    return out


def sold_after_death(bb: dict, estate: dict) -> str:
    """'' or 'sold YYYY-MM-DD' when the parcel's last sale postdates the
    decedent's death (backbone last_sale_date=YYYYMMDD, estate DOD=MM/DD/YYYY)."""
    sale = (bb.get("last_sale_date") or "").strip()
    dod = (estate.get("date_of_death") or "").strip()
    if len(sale) != 8 or not sale.isdigit() or not dod:
        return ""
    try:
        dod_dt = datetime.strptime(dod, "%m/%d/%Y")
        sale_dt = datetime.strptime(sale, "%Y%m%d")
    except ValueError:
        return ""
    if sale_dt > dod_dt:
        return f"sold {sale_dt.date()}"
    return ""


def load_exported() -> set[str]:
    done: set[str] = set()
    if LEDGER.exists():
        with LEDGER.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    done.add(json.loads(line)["parcel_id"])
    return done


def split_sdat_name(raw: str) -> tuple[str, str]:
    """SDAT owner-of-record names are 'LAST FIRST M' (no comma), often
    'LAST FIRST / LAST FIRST' for co-owners — trace the first person."""
    raw = (raw or "").split("/")[0].strip()
    if "," in raw or not raw:
        return split_owner_name(raw)
    first, last = split_owner_name(raw)
    if not first:  # entity or single token — keep as-is
        return first, last
    parts = raw.split()
    return " ".join(parts[1:]), parts[0]


def ownership_flag(decedent: str, owner: str) -> str:
    """'hasn't sold yet' check: decedent surname still in the owner of record?"""
    if not owner:
        return "no-owner-on-record"
    if not decedent:
        return ""
    surname = decedent.split(",")[0].strip().upper()
    return "decedent-still-owner" if surname and surname in owner.upper() else "TRANSFERRED?"


def build_row(lead: dict, facts: dict, matches: dict, bb: dict) -> dict:
    state = "DC" if "DC" in (lead.get("jurisdiction") or "").upper() else "MD"
    parcel = (lead.get("parcel_id") or "").strip()
    details = lead.get("details") or ""

    estate = {}
    m = _ESTATE_RE.search(details)
    if m:
        estate = facts.get(m.group(1), {"estate_no": m.group(1), "decedent_name": m.group(2)})
    match = matches.get(parcel, {})
    decedent = (estate.get("decedent_name") or match.get("decedent_name") or "").strip()
    owner_from_lead = (lead.get("owner_name") or "").strip()
    owner_from_match = (match.get("owner_name") or "").strip() or (bb.get("owner_name") or "").strip()
    current_owner = owner_from_lead or owner_from_match
    flag = ownership_flag(decedent, current_owner) if "probate" in (lead.get("signals") or "") else ""
    sold = sold_after_death(bb, estate) if "probate" in (lead.get("signals") or "") else ""
    if sold:
        flag = f"TRANSFERRED ({sold})"

    # Skip-trace target: the decedent when they're still owner of record
    # (DataSift traces relatives/heirs), else the owner of record. SDAT match
    # names are LAST-first; lead_score owner names are 'LAST, FIRST' or entity.
    if decedent and flag == "decedent-still-owner":
        first, last = split_owner_name(decedent)
    elif owner_from_lead:
        first, last = split_owner_name(owner_from_lead)
    elif owner_from_match:
        first, last = split_sdat_name(owner_from_match)
    else:
        first, last = split_owner_name(decedent)
    if last == "Unknown Owner":
        first, last = "", ""

    ps, pc, pst, pz = split_address(lead.get("situs_address") or bb.get("situs_address") or "", state)
    pc = pc or (bb.get("situs_city") or "").strip()
    pz = pz or (bb.get("situs_zip") or "").strip()
    ms, mc, mst, mz = split_address(
        lead.get("owner_mailing_address") or bb.get("owner_mailing_address") or "", state)

    row = {
        "FirstName": first, "LastName": last,
        "MailingStreet": ms, "MailingCity": mc, "MailingState": mst, "MailingZip": mz,
        "PropertyStreet": ps, "PropertyCity": pc, "PropertyState": pst, "PropertyZip": pz,
        "APN": parcel, "Jurisdiction": lead.get("jurisdiction") or "",
        "Score": lead.get("score") or "", "Signals": lead.get("signals") or "",
        "EstateNo": estate.get("estate_no", ""), "DecedentName": decedent,
        "EstateStatus": estate.get("status", ""), "FilingDate": estate.get("filing_date", ""),
        "DateOfDeath": estate.get("date_of_death", ""),
        "PersonalRep": estate.get("personal_rep_name", ""),
        "CurrentOwner": current_owner,
        "OwnershipFlag": flag,
        "Details": details,
    }
    return {k: clean_text(v) for k, v in row.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lead-score", type=Path, default=DEFAULT_LEAD_SCORE)
    ap.add_argument("--signals", default="probate,preforeclosure",
                    help="comma list; a lead is kept if ANY of its signals is listed")
    ap.add_argument("--include-taxlien", action="store_true",
                    help="also keep tax-lien-only leads (9.8k rows — founder said not yet)")
    ap.add_argument("--min-score", type=int, default=None)
    ap.add_argument("--max-rows", type=int, default=None)
    ap.add_argument("--all", action="store_true", help="ignore the exported ledger (full re-export)")
    ap.add_argument("--dry-run", action="store_true", help="count + preview only, write nothing")
    args = ap.parse_args()

    wanted = {s.strip().lower() for s in args.signals.split(",") if s.strip()}
    if args.include_taxlien:
        wanted.add("taxlien")
    facts, matches = load_probate()
    exported = set() if args.all else load_exported()

    if not args.lead_score.exists():
        print(f"! lead_score.csv not found at {args.lead_score}")
        return 1

    leads: list[dict] = []
    skipped_done = 0
    with args.lead_score.open(newline="", encoding="utf-8") as fh:
        for lead in csv.DictReader(fh):  # sorted by score desc
            signals = {s.strip().lower() for s in (lead.get("signals") or "").split(";") if s.strip()}
            if not signals & wanted:
                continue
            if args.min_score is not None and int(lead.get("score") or 0) < args.min_score:
                continue
            if (lead.get("parcel_id") or "").strip() in exported:
                skipped_done += 1
                continue
            leads.append(lead)
            if args.max_rows is not None and len(leads) >= args.max_rows:
                break

    backbone = load_backbone({(l.get("parcel_id") or "").strip() for l in leads})
    rows = [build_row(l, facts, matches, backbone.get((l.get("parcel_id") or "").strip(), {}))
            for l in leads]

    stamp = datetime.now(timezone.utc)
    print(f"skip-trace export: {len(rows)} new lead(s) "
          f"(signals={sorted(wanted)}, already-exported skipped={skipped_done})")
    if not rows:
        return 0
    if args.dry_run:
        for r in rows[:5]:
            print(f"  {r['LastName']!r:30} {r['PropertyStreet']!r:32} {r['Signals']} flag={r['OwnershipFlag']}")
        print("  (dry-run: nothing written)")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"skiptrace-{stamp.strftime('%Y%m%d-%H%M')}.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in COLUMNS])

    with LEDGER.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({
                "parcel_id": r["APN"], "exported_at": stamp.isoformat(), "file": out.name,
            }) + "\n")
    print(f"wrote {out}  ({len(rows)} rows) — upload to DataSift, then import results to FUB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
