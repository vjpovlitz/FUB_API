from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fub_api.client import FUBClient


class Resource:
    """Base for FUB list resources.

    All FUB collections page the same way: a `next` cursor token (opaque
    base64, decodes to {"sinceId": N}) carried at `_metadata.next`. Subclasses
    set PATH, COLLECTION (the response key), and optionally DEFAULT_FIELDS
    (People needs `allFields`; Deals 400s on it).
    """

    PATH: str = ""
    COLLECTION: str = ""
    DEFAULT_FIELDS: str | None = None
    DEFAULT_PARAMS: dict[str, Any] = {}  # always-applied query params

    def __init__(self, client: FUBClient):
        self._client = client

    def _request(self, method: str, path: str, **kwargs):
        return self._client.request(method, path, **kwargs)

    def list(
        self,
        *,
        limit: int = 100,
        next_token: str | None = None,
        fields: str | None = None,
        **filters: Any,
    ) -> dict:
        params: dict[str, Any] = {**self.DEFAULT_PARAMS, "limit": min(limit, 100), **filters}
        f = fields if fields is not None else self.DEFAULT_FIELDS
        if f:
            params["fields"] = f
        if next_token:
            params["next"] = next_token
        return self._request("GET", self.PATH, params=params)

    def get(self, entity_id: int | str) -> dict:
        return self._request("GET", f"{self.PATH}/{entity_id}")

    def page(
        self,
        *,
        limit: int = 100,
        next_token: str | None = None,
        fields: str | None = None,
        **filters: Any,
    ) -> tuple[list[dict], str | None]:
        """Return (rows, next_token). next_token=None means no more pages.

        An empty result array marks the end even if a stale `next` is echoed.
        """
        resp = self.list(limit=limit, next_token=next_token, fields=fields, **filters)
        rows = resp.get(self.COLLECTION) or []
        meta = resp.get("_metadata") or {}
        if not rows:
            return [], None
        return rows, (meta.get("next") or None)
