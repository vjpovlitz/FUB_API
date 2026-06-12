"""Production Niche -> FUB push (idempotent, all foreclosure/probate notices).

Pulls Niche notices and upserts each into FUB via `fub_api.pusher.FubPusher`:
re-runs skip unchanged leads, update changed ones, and create only new ones, so
this is safe to run 3x/day. Mapping (person/note/relationships/custom fields) is
reused verbatim from the proven `niche_to_fub_test` module; only the source and
tags differ (production source + signal/umbrella tags instead of the test tag).

  python scripts/push_niche_to_fub.py             # dry-run, all notices
  python scripts/push_niche_to_fub.py --push      # live upsert
  python scripts/push_niche_to_fub.py --push -n 2 # live, first 2 (smoke)
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fub_api import FUBClient  # noqa: E402
from fub_api.alerts import send_alert  # noqa: E402
from fub_api.pusher import FubPusher, Ledger, signal_tag, split_owner_name, TAG_FORECLOSURE  # noqa: E402
from niche_api import NicheClient  # noqa: E402
import niche_to_fub_test as nt  # noqa: E402  (reuse the proven mappers)

NICHE_SOURCE = "Niche Foreclosure Feed"
# Niche's current dataset is all `Foreclosures`; pull both types so probate is
# covered the moment that slug returns rows.
NICHE_TYPES = "foreclosures,pre-probate,probate"

# Quality filter (founder, 2026-06-10): he bulk-deleted 5,756 old Niche leads —
# the feed reaches back to early 2024 and many properties had already sold.
# Only push notices filed in the last ~8 months that haven't sold yet. The API
# ignores date filters server-side, so this is applied client-side.
MAX_AGE_DAYS = 244  # ~8 months


def drop_reason(rec: dict, today: date) -> str | None:
    """None if the notice should be pushed, else why it's dropped.

    "Hasn't sold yet" uses the only signals the feed carries: an explicit
    saleStatus of sold, or an auction date that already passed with no status
    update (cancelled/postponed auctions didn't happen, so those stay).
    """
    filed = (rec.get("date") or "")[:10]
    if not filed or filed < (today - timedelta(days=MAX_AGE_DAYS)).isoformat():
        return "old"
    status = (rec.get("saleStatus") or "").strip().lower()
    if status == "sold":
        return "sold"
    sale = (rec.get("dateOfSale") or "")[:10]
    if sale and sale < today.isoformat() and not status:
        return "auction-passed"
    return None


# --- Update visibility + owner alerts (founder, 2026-06-10) -------------------
# Field changes always PUT to the person; sale-critical changes ALSO append a
# timeline note, and high-equity leads additionally alert the owner (FUB task
# assigned to them + the ALERT_WEBHOOK_URL channel from fub_api.alerts).
# These are read at import time, so load .env here (main() runs from_env later).
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
SOLD_TAG = "niche⚡️ sold"
# FUB user the high-value-lead task is assigned to (set in .env; empty = task
# created unassigned).
ALERT_USER = os.getenv("NICHE_ALERT_USER", "")
ALERT_MIN_EQUITY = int(os.getenv("NICHE_ALERT_MIN_EQUITY", "100000"))

_owner_id_cache: list = []  # [resolved id or None]


def sale_meta(rec: dict) -> dict:
    """The sale-critical fields remembered in the ledger for change detection."""
    return {
        "dateOfSale": (rec.get("dateOfSale") or "")[:10],
        "saleStatus": (rec.get("saleStatus") or "").strip().lower(),
    }


def equity(rec: dict) -> float | None:
    raw = (rec.get("propertyDetails") or {}).get("estimatedAvailableEquity")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def is_high_value(rec: dict) -> bool:
    eq = equity(rec)
    return eq is not None and eq >= ALERT_MIN_EQUITY


def describe_changes(old: dict, new: dict) -> list[str]:
    lines = []
    for key, label in (("dateOfSale", "Sale date"), ("saleStatus", "Sale status")):
        if old.get(key, "") != new.get(key, ""):
            lines.append(f"{label}: {old.get(key) or 'n/a'} -> {new.get(key) or 'n/a'}")
    return lines


def _owner_user_id(fub: FUBClient):
    if not ALERT_USER:
        return None
    if not _owner_id_cache:
        try:
            users = fub.request("GET", "/users", params={"limit": 100}).get("users") or []
            _owner_id_cache.append(next(
                (u["id"] for u in users if (u.get("name") or "").strip().lower() == ALERT_USER.lower()), None))
        except Exception:
            _owner_id_cache.append(None)
    return _owner_id_cache[0]


def alert_owner(pusher: FubPusher, fub_id, rec: dict, subject: str, detail: str) -> None:
    """High-value-lead alert: FUB task on the lead (assigned to the owner, due
    today -> native FUB notification) + the env-configured webhook channel."""
    send_alert(subject, detail)
    if pusher.dry_run:
        return
    try:
        body = {"personId": fub_id, "name": subject,
                "dueDate": date.today().isoformat(), "type": "Follow Up"}
        owner = _owner_user_id(pusher.fub)
        if owner:
            body["assignedUserId"] = owner
        pusher.fub.request("POST", "/tasks", json=body)
    except Exception as exc:  # alerting must never break the push
        pusher.log(f"  ! owner-alert task failed for {fub_id}: {exc}")


def note_sale_change(pusher: FubPusher, fub_id, rec: dict, changes: list[str], now: str) -> None:
    addr = rec.get("address") or ""
    body = "\n".join([f"Property: {addr}", *changes, f"(auto-update {now[:10]})"])
    if pusher.dry_run:
        pusher.log(f"  [niche:{rec.get('_id')}] would note sale change: {'; '.join(changes)}")
    else:
        try:
            pusher.fub.request("POST", "/notes", json={
                "personId": fub_id, "subject": f"Sale update: {'; '.join(changes)}",
                "body": body, "isHtml": False})
        except Exception as exc:
            pusher.log(f"  ! sale-change note failed for {fub_id}: {exc}")
    if is_high_value(rec):
        alert_owner(pusher, fub_id, rec, f"High-value lead update: {addr}",
                    "\n".join(changes) + f"\nEstimated equity: {equity(rec):,.0f}")


def retire(pusher: FubPusher, external_id: str, prior: dict, rec: dict, reason: str, now: str) -> None:
    """A previously pushed lead is now sold / past auction: tag it + note it
    (once) instead of silently abandoning it. Ledger hash 'retired:<reason>'
    marks it done so re-runs don't repeat this."""
    fub_id = prior.get("fub_id")
    label = "marked sold" if reason == "sold" else f"auction passed {(rec.get('dateOfSale') or '')[:10]}"
    if pusher.dry_run:
        pusher.log(f"  [{external_id}] would retire ({label})")
        return
    try:
        merged = sorted(set(pusher._existing_tags(fub_id)) | {SOLD_TAG})
        pusher.fub.request("PUT", f"/people/{fub_id}", json={"tags": merged})
        pusher.fub.request("POST", "/notes", json={
            "personId": fub_id, "subject": f"Niche: property {label} — lead retired",
            "body": f"Property: {rec.get('address') or ''}\n{label}\n"
                    f"No further automatic updates will be pushed.", "isHtml": False})
        pusher.ledger.record(external_id, fub_id, f"retired:{reason}", now, meta=sale_meta(rec))
        if is_high_value(rec):
            alert_owner(pusher, fub_id, rec, f"High-value lead retired ({label}): {rec.get('address') or ''}",
                        f"Estimated equity: {equity(rec):,.0f}")
    except Exception as exc:
        pusher.log(f"  ! retire failed for {external_id}: {exc}")


def build(rec: dict) -> tuple[str, dict, list[str], dict | None, list[dict]]:
    """Niche notice -> (external_id, person_body, signal_tags, note, relationships)."""
    external_id = f"niche:{rec.get('_id')}"
    body = nt.map_person(rec)
    body.pop("source", None)   # pusher stamps the production source
    body.pop("tags", None)     # pusher stamps signal + umbrella tags
    if "name" in body:         # LLC/no-name fallback: FUB rejects top-level `name`
        first, last = split_owner_name(body.pop("name"))
        if first:
            body["firstName"] = first
        body["lastName"] = last
    tag = signal_tag(rec.get("recordType") or "foreclosures") or TAG_FORECLOSURE
    note = nt.map_note(rec)
    rels = nt.map_relationships(rec)
    return external_id, body, [tag], note, rels


def push(pusher: FubPusher, niche: NicheClient, *, limit: int | None, now: str) -> None:
    n = 0
    pushed = 0
    dropped = Counter()
    retired = 0
    change_notes = 0
    today = datetime.now(timezone.utc).date()
    for rec in niche.notices.iterate(type=NICHE_TYPES):
        n += 1
        external_id = f"niche:{rec.get('_id')}"
        reason = drop_reason(rec, today)
        if reason:
            dropped[reason] += 1
            # A lead we already pushed that is now sold/past-auction gets tagged
            # + noted once, so agents see it's dead instead of it going silent.
            if reason in ("sold", "auction-passed"):
                prior = pusher.ledger.get(external_id)
                if prior and prior.get("fub_id") is not None \
                        and not str(prior.get("content_hash", "")).startswith("retired:"):
                    retire(pusher, external_id, prior, rec, reason, now)
                    retired += 1
            continue
        prior = pusher.ledger.get(external_id)
        old_meta = (prior or {}).get("meta") or {}
        new_meta = sale_meta(rec)
        _, body, tags, note, rels = build(rec)
        fub_id = pusher.upsert(external_id, body, tags, note=note, relationships=rels,
                               meta=new_meta, now=now)
        if prior and old_meta and old_meta != new_meta:
            changes = describe_changes(old_meta, new_meta)
            if changes and (fub_id is not None or pusher.dry_run):
                note_sale_change(pusher, fub_id, rec, changes, now)
                change_notes += 1
        pushed += 1
        if limit is not None and pushed >= limit:
            break
        if pushed % 200 == 0:
            pusher.log(f"  ...niche {pushed} pushed / {n} seen ({pusher.stats})")
    pusher.log(f"Niche push done: {n} notices, {pushed} passed filter "
               f"(dropped {dict(dropped)}; retired {retired}; sale-change notes {change_notes}) "
               f"-> {pusher.stats}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="live upsert (default dry-run)")
    ap.add_argument("-n", "--limit", type=int, default=None, help="cap records (smoke test)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    ledger = Ledger()
    niche = NicheClient.from_env()
    fub = FUBClient.from_env() if args.push else None
    pusher = FubPusher(fub, ledger, source=NICHE_SOURCE, dry_run=not args.push)
    print(f"=== Niche -> FUB ({'LIVE' if args.push else 'DRY-RUN'}) source={NICHE_SOURCE!r} ===")
    push(pusher, niche, limit=args.limit, now=now)
    if pusher.stats.failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
