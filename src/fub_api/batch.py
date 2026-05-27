"""BatchExtractor framework: paginate -> shard -> checkpoint -> resume.

Ported from GHL_API. The only structural change is the pagination cursor: FUB
uses a single opaque `next` token string (decodes to {"sinceId": N}) instead of
GHL's (startAfter, startAfterId) tuple. Everything else — sharding, atomic
checkpoint after every page, resume-by-default — is identical.

Resume contract (DATA_RULES §9, and a hard user requirement):
- Checkpoint is rewritten after EVERY page (never batched).
- Writes are atomic: write `<path>.tmp` then `os.replace(tmp, path)`. A crash
  between the two leaves the previous checkpoint intact.
- On restart (resume=True, the default) the extractor reads the checkpoint and
  continues into the current shard, rolling to the next when it fills. It does
  NOT truncate partial shards — the audit gate catches real corruption.

CSV format (DATA_RULES §5): UTF-8 with BOM, CRLF, csv.QUOTE_MINIMAL, one file
per shard named `<Entity>_part_NNN.csv`.
"""
from __future__ import annotations

import csv
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from fub_api.client import FUBClient
from fub_api.mappers import PEOPLE_COLUMNS, map_person

DEFAULT_SHARD_SIZE = 5_000


def _now_utc_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


@dataclass
class Checkpoint:
    """Persistent extractor state. Rewritten atomically after every page."""

    entity: str
    extracted_at_utc: str
    cursor: Any | None = None          # FUB `next` token (str) or None
    shard_index: int = 1
    rows_in_current_shard: int = 0
    rows_total: int = 0
    pages_fetched: int = 0
    finished: bool = False
    shard_files: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> Checkpoint | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            entity=data["entity"],
            extracted_at_utc=data["extracted_at_utc"],
            cursor=data.get("cursor"),
            shard_index=int(data.get("shard_index", 1)),
            rows_in_current_shard=int(data.get("rows_in_current_shard", 0)),
            rows_total=int(data.get("rows_total", 0)),
            pages_fetched=int(data.get("pages_fetched", 0)),
            finished=bool(data.get("finished", False)),
            shard_files=list(data.get("shard_files", [])),
        )

    def save(self, path: Path) -> None:
        payload = {
            "entity": self.entity,
            "extracted_at_utc": self.extracted_at_utc,
            "cursor": self.cursor,
            "shard_index": self.shard_index,
            "rows_in_current_shard": self.rows_in_current_shard,
            "rows_total": self.rows_total,
            "pages_fetched": self.pages_fetched,
            "finished": self.finished,
            "shard_files": self.shard_files,
            "updated_at_utc": _now_utc_iso(),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # atomic


class BatchExtractor(ABC):
    """Subclass to wire up a specific entity. See PeopleExtractor below."""

    entity: str = "Entity"
    columns: list[str] = []

    def __init__(
        self,
        client: FUBClient,
        *,
        output_dir: Path,
        shard_size: int = DEFAULT_SHARD_SIZE,
        page_limit: int = 100,
    ):
        self.client = client
        self.output_dir = output_dir
        self.shard_size = shard_size
        self.page_limit = page_limit
        self.checkpoint_path = output_dir / f"{self.entity}.checkpoint.json"

    @abstractmethod
    def fetch_page(self, cursor: Any | None) -> tuple[list[dict], Any | None]:
        """Return (api_rows, next_cursor). next_cursor=None means done."""

    @abstractmethod
    def map_row(self, api_row: dict, *, extracted_at: str) -> dict:
        """Map and sanitize one API row to a CSV row dict."""

    # ---- framework ----

    def run(self, *, max_rows: int | None = None, resume: bool = True) -> Checkpoint:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        cp = Checkpoint.load(self.checkpoint_path) if resume else None
        if cp is None:
            cp = Checkpoint(entity=self.entity, extracted_at_utc=_now_utc_iso())

        if cp.finished:
            print(f"[{self.entity}] checkpoint says finished — nothing to do "
                  f"({cp.rows_total:,} rows across {len(cp.shard_files)} shards).")
            return cp

        print(f"[{self.entity}] starting (resume={resume}, "
              f"rows_total={cp.rows_total:,}, shard={cp.shard_index}, "
              f"in_shard={cp.rows_in_current_shard}).")

        try:
            while True:
                if max_rows is not None and cp.rows_total >= max_rows:
                    break

                api_rows, next_cursor = self.fetch_page(cp.cursor)
                cp.pages_fetched += 1

                if not api_rows:
                    cp.finished = next_cursor is None
                    cp.cursor = next_cursor
                    cp.save(self.checkpoint_path)
                    break

                if max_rows is not None:
                    remaining = max_rows - cp.rows_total
                    if remaining <= 0:
                        break
                    if len(api_rows) > remaining:
                        api_rows = api_rows[:remaining]

                rows = [self.map_row(r, extracted_at=cp.extracted_at_utc) for r in api_rows]
                self._write_rows(rows, cp)

                cp.cursor = next_cursor
                if next_cursor is None:
                    cp.finished = True
                cp.save(self.checkpoint_path)  # atomic, after every page

                print(f"[{self.entity}] page={cp.pages_fetched:>4} "
                      f"+{len(rows):>4} rows  total={cp.rows_total:>7,}  "
                      f"shard={cp.shard_index:>3}  "
                      f"burst_rem={self.client.throttle.burst_remaining}")

                if cp.finished:
                    break
        finally:
            cp.save(self.checkpoint_path)

        return cp

    def _write_rows(self, rows: Iterable[dict], cp: Checkpoint) -> None:
        pending = list(rows)
        i = 0
        while i < len(pending):
            room = self.shard_size - cp.rows_in_current_shard
            batch = pending[i:i + room]
            shard_path = self._shard_path(cp.shard_index)
            self._append_csv(shard_path, batch)
            if shard_path.name not in cp.shard_files:
                cp.shard_files.append(shard_path.name)

            cp.rows_in_current_shard += len(batch)
            cp.rows_total += len(batch)
            i += len(batch)

            if cp.rows_in_current_shard >= self.shard_size:
                cp.shard_index += 1
                cp.rows_in_current_shard = 0

    def _shard_path(self, index: int) -> Path:
        return self.output_dir / f"{self.entity}_part_{index:03d}.csv"

    def _append_csv(self, path: Path, rows: list[dict]) -> None:
        new_file = not path.exists()
        if new_file:
            path.write_bytes(b"\xef\xbb\xbf")  # BOM for new files only
        with path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=self.columns,
                lineterminator="\r\n",
                quoting=csv.QUOTE_MINIMAL,
                extrasaction="ignore",
            )
            if new_file:
                writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in self.columns})


# ---------- Per-entity extractors ----------

class PeopleExtractor(BatchExtractor):
    entity = "People"
    columns = PEOPLE_COLUMNS

    def fetch_page(self, cursor):
        # cursor is the FUB `next` token (str) or None for the first page.
        rows, next_token = self.client.people.page(
            limit=min(self.page_limit, 100), next_token=cursor
        )
        return rows, next_token

    def map_row(self, api_row, *, extracted_at):
        return map_person(api_row, extracted_at=extracted_at)
