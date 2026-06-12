"""Small, reversible test: push a few Niche foreclosure notices into FUB.

Pulls N newest `foreclosures` from Niche, maps each to a FUB person (+ a note
carrying the foreclosure detail), and creates them in the LIVE FUB account.

Safety:
  - DRY-RUN by default: prints the exact POST bodies and writes NOTHING. You
    must pass --push to actually create records.
  - Test leads use a NEUTRAL source (`Niche API Test`) that won't match real
    lead-flow rules, plus a loud DELETE tag (`ZZ_NICHE_TEST_DELETE`) so they're
    trivial to find and bulk-delete afterward.
  - Prints each created person's id + direct app URL for verification.

Usage:
    python scripts/niche_to_fub_test.py            # dry-run, 3 records
    python scripts/niche_to_fub_test.py --push     # actually create them
    python scripts/niche_to_fub_test.py -n 1 --push
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fub_api import FUBClient  # noqa: E402  (also injects OS trust store)
from niche_api import NicheClient  # noqa: E402

TEST_SOURCE = "Niche API Test"
TEST_TAG = "ZZ_NICHE_TEST_DELETE"
APP_PERSON_URL = "https://app.followupboss.com/2/people/view/{id}"

# Niche -> FUB custom-field map. Every custom field below ALREADY exists on the
# FUB account (verified live via GET /customFields), so the push just sets them
# by name. Keys = FUB custom-field name; values = Niche propertyDetails key.
#
# Number-typed FUB fields — cast so FUB stores them numerically (equity can be
# negative).
NUMBER_CUSTOM_FIELDS = {
    "customEstimatedAvailableEquity": "estimatedAvailableEquity",  # Estimated Equity
    "customEstimatedLoanBalance": "totalEstimatedLoanBalance",      # Estimated Loan Balance
}
# Text-typed FUB fields sourced straight from propertyDetails.
TEXT_PD_CUSTOM_FIELDS = {
    "customInterestRate": "mtgInterestRate",               # Interest Rate
    "customMortgageAmount": "mtgAmount",                   # Mortgage Amount
    "customMortgagee": "lenderName",                       # Mortgagee (lender of record)
    "customLTVRatio": "ltv",                               # LTV Ratio
    "customLengthOfOwnership": "lengthOfOwnership",        # Length of Ownership
    "customPropertyCondition": "constructionQualityType",  # Property Condition
}

# Niche returns many phones/relatives (up to ~20); cap to the most useful so FUB
# records stay clean. Owner phones rank by Niche `score`; relatives keep only
# those with a phone (the actionable ones).
MAX_OWNER_PHONES = 5
MAX_OWNER_EMAILS = 3
MAX_RELATIONSHIPS = 5

# Niche phone-type labels -> FUB phone types.
PHONE_TYPE_MAP = {"residential": "home", "wireless": "mobile", "cell": "mobile",
                  "business": "work", "voip": "mobile", "otherphone": "other",
                  "landline": "home"}


def _split_name(rec: dict) -> tuple[str, str]:
    first = (rec.get("firstName") or "").strip()
    last = (rec.get("lastName") or "").strip()
    if first or last:
        return first, last
    # Fallback (e.g. LLC names): whole thing into lastName so FUB keeps it intact.
    full = (rec.get("fullName") or "").strip()
    return "", full


def _phone_type(t: str | None) -> str:
    t = (t or "").strip().lower()
    return PHONE_TYPE_MAP.get(t, t or "other")


def _dedup_phones(phones: list | None, cap: int) -> list[dict]:
    """Top `cap` distinct phone numbers, highest Niche `score` first."""
    seen: set[str] = set()
    out: list[dict] = []
    for p in sorted(phones or [], key=lambda x: (x.get("score") or -1), reverse=True):
        num = str(p.get("number") or "").strip()
        norm = "".join(c for c in num if c.isdigit())
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append({"value": num, "type": _phone_type(p.get("type"))})
        if len(out) >= cap:
            break
    return out


def _dedup_emails(emails: list | None, cap: int) -> list[dict]:
    """Top `cap` distinct owner emails -> FUB person email entries."""
    seen: set[str] = set()
    out: list[dict] = []
    for e in emails or []:
        addr = str(e.get("address") or "").strip()
        key = addr.lower()
        if not addr or key in seen:
            continue
        seen.add(key)
        out.append({"value": addr, "type": "home"})
        if len(out) >= cap:
            break
    return out


def _custom_fields(rec: dict) -> dict:
    """All Niche -> FUB custom-field values (financials + property profile).

    Every key here is an existing FUB custom field. Empty/None Niche values are
    skipped so we never overwrite a FUB field with a blank.
    """
    pd = rec.get("propertyDetails") or {}
    owner = rec.get("owner") or {}
    out: dict = {}
    for fub_key, niche_key in NUMBER_CUSTOM_FIELDS.items():
        raw = pd.get(niche_key)
        if raw in (None, ""):
            continue
        # FUB `number` custom fields accept INTEGERS only (negatives OK); a float
        # value is silently dropped. Round to the nearest whole dollar.
        try:
            out[fub_key] = int(round(float(raw)))
        except (TypeError, ValueError):
            continue
    for fub_key, niche_key in TEXT_PD_CUSTOM_FIELDS.items():
        raw = pd.get(niche_key)
        if raw not in (None, ""):
            out[fub_key] = str(raw).strip()
    dos = (rec.get("dateOfSale") or "").strip()
    if dos:
        out["customDateOfSale"] = dos                       # FUB date field
    status = (rec.get("saleStatus") or "").strip()
    if status:
        out["customSaleStatus"] = status                    # field created via API 2026-06-10
    absentee = pd.get("absenteeOwned")
    if absentee is not None:
        out["customOccupancy"] = "Absentee" if absentee else "Owner Occupied"
    deceased = owner.get("deceaced")                        # (Niche's spelling)
    if deceased is not None:
        out["customHomeownerDeceased"] = "Yes" if deceased else "No"
    rent = (rec.get("zillow") or {}).get("rentalZestimate")
    if rent not in (None, ""):
        out["customMonthlyRent"] = str(rent).strip()
    return out


def map_person(rec: dict, max_phones: int = MAX_OWNER_PHONES,
               max_emails: int = MAX_OWNER_EMAILS) -> dict:
    """Niche foreclosure notice -> FUB person create body."""
    first, last = _split_name(rec)
    body: dict = {
        "source": TEST_SOURCE,
        "tags": [TEST_TAG],
    }
    if first:
        body["firstName"] = first
    if last:
        body["lastName"] = last
    if not (first or last):
        body["name"] = (rec.get("fullName") or "Unknown").strip()
    addresses: list[dict] = []
    street = (rec.get("street") or "").strip()
    if street:
        addresses.append({
            "type": "property",
            "street": street,
            "city": (rec.get("city") or "").strip(),
            "state": (rec.get("state") or "").strip(),
            "code": (rec.get("zipCode") or "").strip(),
        })
    # Absentee-owner mailing address (distinct from the property) -> 2nd address.
    ma = (rec.get("propertyDetails") or {}).get("mailingAddress") or {}
    ma_street = (ma.get("street") or "").strip()
    if ma_street and ma_street.upper() != street.upper():
        addresses.append({
            "type": "mailing",
            "street": ma_street,
            "city": (ma.get("city") or "").strip(),
            "state": (ma.get("state") or "").strip(),
            "code": (ma.get("zip") or "").strip(),
        })
    if addresses:
        body["addresses"] = addresses
    owner = rec.get("owner") or {}
    phones = _dedup_phones(owner.get("phones"), max_phones)
    if phones:
        body["phones"] = phones
    emails = _dedup_emails(owner.get("emails"), max_emails)
    if emails:
        body["emails"] = emails
    body.update(_custom_fields(rec))
    return body


def map_relationships(rec: dict, max_rel: int = MAX_RELATIONSHIPS) -> list[dict]:
    """Niche `family` members -> FUB peopleRelationships bodies.

    `personId` is filled in after the person is created. Only relatives with a
    phone number are kept (those are the actionable contacts), capped to
    `max_rel`. These land under the lead's "Relationships" column in FUB.
    """
    out: list[dict] = []
    for fam in rec.get("family") or []:
        ph = fam.get("phone") or {}
        num = str(ph.get("number") or "").strip()
        name = (fam.get("name") or "").strip()
        if not num or not name:
            continue
        # NB: FUB's /peopleRelationships rejects a `name` field (400) — it derives
        # the display name from firstName/lastName. Send only the parts.
        parts = name.split()
        rel = {
            "firstName": parts[0] if parts else name,
            "lastName": " ".join(parts[1:]),
            "type": (fam.get("subType") or "Relative").strip().title() or "Relative",
            "phones": [{"value": num, "type": _phone_type(ph.get("type"))}],
        }
        out.append(rel)
        if len(out) >= max_rel:
            break
    return out


def map_note(rec: dict) -> dict:
    """Foreclosure detail as a FUB note body (personId filled in after create)."""
    lines = [
        f"Record type:  {rec.get('recordType')}",
        f"County:       {rec.get('county')}, {rec.get('state')}",
        f"Property:     {rec.get('address')}",
        f"Sale date:    {rec.get('dateOfSale')}   (sale time: {rec.get('saleTime') or 'n/a'})",
        f"Sale status:  {rec.get('saleStatus') or 'n/a'}",
        f"Filed/notice: {rec.get('date')}",
        f"Attorney:     {rec.get('attorney') or 'n/a'}",
        f"Mortgagee:    {rec.get('mortgagee') or 'n/a'}",
        f"Niche id:     {rec.get('_id')}",
    ]
    return {
        "subject": f"Foreclosure notice - sale {rec.get('dateOfSale')} ({rec.get('county')})",
        "body": "\n".join(lines),
        "isHtml": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=3, help="records to push (default 3)")
    ap.add_argument("--push", action="store_true", help="actually create records (default dry-run)")
    ap.add_argument("--no-note", action="store_true", help="skip the per-person foreclosure note")
    ap.add_argument("--no-relationships", action="store_true",
                    help="skip pushing relatives to FUB peopleRelationships")
    ap.add_argument("--max-phones", type=int, default=MAX_OWNER_PHONES,
                    help=f"max owner phones per person (default {MAX_OWNER_PHONES})")
    ap.add_argument("--max-relatives", type=int, default=MAX_RELATIONSHIPS,
                    help=f"max relatives per person (default {MAX_RELATIONSHIPS})")
    args = ap.parse_args()

    niche = NicheClient.from_env()
    recs = list(niche.notices.iterate(type="foreclosures", max_records=args.count))
    print(f"Pulled {len(recs)} Niche foreclosure record(s).\n")

    mode = "PUSH (live writes)" if args.push else "DRY-RUN (no writes)"
    print("=" * 72)
    print(f"  MODE: {mode}   source={TEST_SOURCE!r}  tag={TEST_TAG!r}")
    print("=" * 72)

    fub = FUBClient.from_env() if args.push else None
    created = []
    for i, rec in enumerate(recs, 1):
        person_body = map_person(rec, max_phones=args.max_phones)
        note_body = None if args.no_note else map_note(rec)
        rels = [] if args.no_relationships else map_relationships(rec, max_rel=args.max_relatives)
        print(f"\n--- [{i}] {rec.get('fullName')}  ({rec.get('county')}) ---")
        print("  POST /people  ->", json.dumps(person_body, ensure_ascii=False))
        if note_body:
            print("  POST /notes   ->", json.dumps({**note_body, "personId": "<new>"}, ensure_ascii=False))
        for rel in rels:
            print("  POST /peopleRelationships ->",
                  json.dumps({**rel, "personId": "<new>"}, ensure_ascii=False))

        if not args.push:
            continue

        resp = fub.request("POST", "/people", json=person_body)
        pid = resp.get("id") if isinstance(resp, dict) else None
        print(f"  -> created person id={pid}  {APP_PERSON_URL.format(id=pid)}")
        created.append(pid)
        if note_body and pid:
            note_resp = fub.request("POST", "/notes", json={**note_body, "personId": pid})
            print(f"  -> note id={note_resp.get('id') if isinstance(note_resp, dict) else '?'}")
        for rel in rels:
            if not pid:
                break
            rel_resp = fub.request("POST", "/peopleRelationships", json={**rel, "personId": pid})
            rid = rel_resp.get("id") if isinstance(rel_resp, dict) else "?"
            who = f"{rel['firstName']} {rel['lastName']}".strip()
            print(f"  -> relationship id={rid}  ({who})")

    if not args.push:
        print("\nDRY-RUN complete. Re-run with --push to create these in FUB.")
    else:
        print(f"\nCreated {len(created)} person(s): {created}")
        print(f"Find/clean up in FUB by tag '{TEST_TAG}' or source '{TEST_SOURCE}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
