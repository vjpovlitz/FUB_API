"""`/notices` resource — list (filter/sort/paginate) + get one.

Filters (per the API docs): type, state, county, city, zipCode, address,
saleStatus, id, plus date ranges dateOfSale / createdAt / updatedAt using
bracketed keys (`createdAt[after]`, `dateOfSale[before]`) and sorting via
`order[field]=asc|desc`.

Pass plain filters as kwargs; pass bracketed/range filters via `extra` (a dict
whose keys are used verbatim), e.g.:

    notices.iterate(state="MD", type="foreclosures,lis-pendens-or-nod",
                    extra={"createdAt[after]": "2026-05-01",
                           "order[createdAt]": "desc"})
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

from niche_api.resources import _base

if TYPE_CHECKING:
    from niche_api.client import NicheClient

PATH = "/notices"

# API Platform default page size is 30; cap explicit requests to be polite.
DEFAULT_PAGE_SIZE = 50


class Notices:
    def __init__(self, client: NicheClient):
        self._client = client

    def list(
        self,
        *,
        page: int = 1,
        items_per_page: int = DEFAULT_PAGE_SIZE,
        extra: dict[str, Any] | None = None,
        **filters: Any,
    ) -> Any:
        params: dict[str, Any] = {"page": page, "itemsPerPage": items_per_page}
        params.update({k: v for k, v in filters.items() if v is not None})
        if extra:
            params.update({k: v for k, v in extra.items() if v is not None})
        return self._client.request("GET", PATH, params=params)

    def get(self, notice_id: int | str) -> dict:
        return self._client.request("GET", f"{PATH}/{notice_id}")

    def iterate(
        self,
        *,
        items_per_page: int = DEFAULT_PAGE_SIZE,
        max_records: int | None = None,
        extra: dict[str, Any] | None = None,
        **filters: Any,
    ) -> Iterator[dict]:
        """Yield notice records across all pages.

        Walks `hydra:next` when present; otherwise increments `page` until a
        page comes back empty or `hydra:totalItems` is reached. Stops at
        `max_records` if given.
        """
        yielded = 0
        page = 1
        while True:
            resp = self.list(page=page, items_per_page=items_per_page, extra=extra, **filters)
            rows = _base.members(resp)
            if not rows:
                return
            for row in rows:
                yield row
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return

            total = _base.total_items(resp)
            if total is not None and yielded >= total:
                return
            # Prefer the server's next link; fall back to page increment.
            if _base.next_path(resp) is None and len(rows) < items_per_page:
                return
            page += 1

    def count(self, *, extra: dict[str, Any] | None = None, **filters: Any) -> int | None:
        """Total matching records (hydra:totalItems) without paging through."""
        resp = self.list(page=1, items_per_page=1, extra=extra, **filters)
        return _base.total_items(resp)
