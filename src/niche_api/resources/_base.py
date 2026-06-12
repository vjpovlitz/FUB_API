"""Collection envelope helpers for the Niche API.

The live backend is a **JSON:API** server (`application/vnd.api+json`):
collections carry `data` (a list of resource objects `{id, type, attributes}`),
`meta.totalItems` / `meta.currentPage`, and `links.next`. Records are flattened
here so resources/mappers see a single flat dict (the `attributes`, plus the
resource `id`/`type` preserved as `ResourceId`/`ResourceType`).

We also still recognize Hydra/JSON-LD (`hydra:member`, `hydra:totalItems`,
`hydra:view.hydra:next`) and plain arrays, so the helpers stay portable if the
content negotiation ever changes.
"""
from __future__ import annotations

from typing import Any


def _flatten(item: Any) -> dict:
    """Flatten a JSON:API resource object into a single dict.

    `{"id": "/notices/1", "type": "Notice", "attributes": {...}}` becomes the
    attributes dict with `ResourceId`/`ResourceType` added. Non-JSON:API dicts
    pass through unchanged.
    """
    if (
        isinstance(item, dict)
        and isinstance(item.get("attributes"), dict)
        and {"id", "type"} <= item.keys()
    ):
        flat = dict(item["attributes"])
        flat.setdefault("ResourceId", item.get("id"))
        flat.setdefault("ResourceType", item.get("type"))
        return flat
    return item if isinstance(item, dict) else {}


def members(resp: Any) -> list[dict]:
    """The collection rows (flattened), whatever the envelope."""
    if isinstance(resp, list):
        return [_flatten(x) for x in resp]
    if not isinstance(resp, dict):
        return []
    # JSON:API + common wrappers (data) and Hydra (hydra:member/member).
    for key in ("data", "hydra:member", "member", "items", "results"):
        rows = resp.get(key)
        if isinstance(rows, list):
            return [_flatten(x) for x in rows]
    return []


def total_items(resp: Any) -> int | None:
    if not isinstance(resp, dict):
        return None
    meta = resp.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("totalItems"), int):
        return meta["totalItems"]
    for key in ("hydra:totalItems", "totalItems"):
        if isinstance(resp.get(key), int):
            return resp[key]
    return None


def next_path(resp: Any) -> str | None:
    """The next-page link (relative path or URL), or None at the last page."""
    if not isinstance(resp, dict):
        return None
    # JSON:API: links.next
    links = resp.get("links")
    if isinstance(links, dict):
        nxt = links.get("next")
        if isinstance(nxt, str) and nxt:
            return nxt
    # Hydra: hydra:view.hydra:next
    view = resp.get("hydra:view") or resp.get("view") or {}
    if isinstance(view, dict):
        nxt = view.get("hydra:next") or view.get("next")
        if isinstance(nxt, str) and nxt:
            return nxt
    return None
