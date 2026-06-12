"""Idempotent FUB lead upsert with a crash-safe local ledger.

The automated imports (Niche foreclosures + RPRD scored leads) run 3x/day, so a
blind ``POST /people`` every run would flood the live CRM with duplicates. This
module keys every lead on a stable **external id** (``niche:<id>`` /
``rprd:<parcel_id>``) recorded in an append-only ledger, so re-runs:

  * **skip** a lead whose content is unchanged (no API call at all),
  * **update** (``PUT /people/{id}``) a lead whose facts changed,
  * **create** (``POST /people``) only genuinely new leads.

Every imported lead carries a per-signal tag plus the umbrella
``niche⚡️ auto-import`` tag so the whole automated load is bulk-deletable from a
single FUB filter (founder requirement, 2026-06-09).

Ledger format: JSON Lines (``data/exports/push_ledger.jsonl``, gitignored). One
line per write, last-wins per external id — O(1) appends, crash-safe (a crash
mid-run never loses already-recorded ids, so we never re-create them as dupes).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fub_api.client import FUBClient

# --- Tags -------------------------------------------------------------------
# Umbrella tag on EVERY pushed lead -> one filter deletes the whole import.
UMBRELLA_TAG = "niche⚡️ auto-import"
TAG_FORECLOSURE = "niche⚡️ foreclosure"
TAG_PROBATE = "niche⚡️ probate"
TAG_TAXLIEN = "niche⚡️ tax-lien"

# Map an RPRD lead_score `signals` token / a Niche recordType -> signal tag.
SIGNAL_TAGS = {
    "foreclosure": TAG_FORECLOSURE,
    "foreclosures": TAG_FORECLOSURE,
    "preforeclosure": TAG_FORECLOSURE,
    "probate": TAG_PROBATE,
    "pre-probate": TAG_PROBATE,
    "taxlien": TAG_TAXLIEN,
    "tax-lien": TAG_TAXLIEN,
}

DEFAULT_LEDGER = Path(__file__).resolve().parent.parent.parent / "data" / "exports" / "push_ledger.jsonl"


def signal_tag(token: str) -> str | None:
    """Resolve a signal/recordType token to its FUB tag (case-insensitive)."""
    return SIGNAL_TAGS.get((token or "").strip().lower())


_ENTITY_TOKENS = (" LLC", " INC", " TRUST", " LP", " LLP", " CORP", " CO ",
                  " ESTATE", " BANK", " ASSOC", " FOUNDATION", " CHURCH")


def split_owner_name(raw: str) -> tuple[str, str]:
    """Best-effort (first, last) split for a FUB person.

    FUB ``POST /people`` rejects a top-level ``name`` field, so every lead needs
    firstName/lastName. Handles "LAST, FIRST" records, plain "First Last", and
    company/estate names (whole string -> lastName so FUB keeps it intact).
    """
    raw = (raw or "").strip()
    if not raw:
        return "", "Unknown Owner"
    if any(tok in f" {raw.upper()} " for tok in _ENTITY_TOKENS):
        return "", raw
    if "," in raw:
        last, _, first = raw.partition(",")
        return first.strip(), last.strip()
    parts = raw.split()
    if len(parts) == 1:
        return "", parts[0]
    return parts[0], " ".join(parts[1:])


def _content_hash(body: dict, tags: list[str]) -> str:
    payload = json.dumps({"body": body, "tags": sorted(tags)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Ledger:
    """Append-only external_id -> FUB-person mapping (JSON Lines)."""

    def __init__(self, path: Path = DEFAULT_LEDGER):
        self.path = Path(path)
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue  # tolerate a torn final line from a crash
                ext = rec.get("external_id")
                if ext:
                    self._entries[ext] = rec  # last line wins

    def get(self, external_id: str) -> dict | None:
        return self._entries.get(external_id)

    def record(self, external_id: str, fub_id: Any, content_hash: str, when: str,
               meta: dict | None = None) -> None:
        rec = {"external_id": external_id, "fub_id": fub_id, "content_hash": content_hash, "ts": when}
        if meta:
            rec["meta"] = meta
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
        self._entries[external_id] = rec


@dataclass
class PushStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (f"created={self.created} updated={self.updated} "
                f"skipped={self.skipped} failed={self.failed}")


class FubPusher:
    """Upsert leads into FUB, deduped via the ledger.

    `source` is the FUB lead source stamped on every created person. `dry_run`
    prints the POST/PUT bodies and writes nothing (ledger untouched).
    """

    def __init__(self, fub: FUBClient, ledger: Ledger, *, source: str,
                 dry_run: bool = False, log: Callable[[str], None] = print):
        self.fub = fub
        self.ledger = ledger
        self.source = source
        self.dry_run = dry_run
        self.log = log
        self.stats = PushStats()

    def _existing_tags(self, fub_id: Any) -> list[str]:
        try:
            resp = self.fub.request("GET", f"/people/{fub_id}", params={"fields": "tags"})
        except Exception:
            return []
        tags = resp.get("tags") if isinstance(resp, dict) else None
        return list(tags) if tags else []

    def upsert(self, external_id: str, body: dict, signal_tags: list[str], *,
               note: dict | None = None, relationships: list[dict] | None = None,
               meta: dict | None = None, now: str) -> Any:
        """Create/update/skip one lead. Returns the FUB person id (or None on dry-run/fail)."""
        tags = sorted({UMBRELLA_TAG, *(t for t in signal_tags if t)})
        full_body = {**body, "source": self.source, "tags": tags}
        chash = _content_hash(body, tags)
        prior = self.ledger.get(external_id)

        if prior and prior.get("content_hash") == chash:
            self.stats.skipped += 1
            return prior.get("fub_id")

        if self.dry_run:
            verb = "PUT (update)" if prior else "POST (create)"
            self.log(f"  [{external_id}] {verb} -> {json.dumps(full_body, ensure_ascii=False)}")
            if note and not prior:
                self.log(f"     +note: {note.get('subject')}")
            if relationships and not prior:
                self.log(f"     +{len(relationships)} relationship(s)")
            return None

        try:
            if prior:  # update existing — union tags so we never clobber manual ones
                fub_id = prior["fub_id"]
                merged = sorted(set(tags) | set(self._existing_tags(fub_id)))
                self.fub.request("PUT", f"/people/{fub_id}", json={**body, "tags": merged})
                self.stats.updated += 1
            else:  # create new — attach note + relationships once, on creation only
                resp = self.fub.request("POST", "/people", json=full_body)
                fub_id = resp.get("id") if isinstance(resp, dict) else None
                if note and fub_id:
                    self.fub.request("POST", "/notes", json={**note, "personId": fub_id})
                for rel in relationships or []:
                    if fub_id:
                        self.fub.request("POST", "/peopleRelationships", json={**rel, "personId": fub_id})
                self.stats.created += 1
            self.ledger.record(external_id, fub_id, chash, now, meta=meta)
            return fub_id
        except Exception as exc:  # one bad lead must not abort the whole run
            self.stats.failed += 1
            self.stats.failures.append(f"{external_id}: {exc}")
            self.log(f"  ! {external_id} failed: {exc}")
            return None
