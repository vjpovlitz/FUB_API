"""Follow Up Boss API client.

Auth: HTTP Basic (API key as username, empty password) plus X-System headers.
Pagination: most list endpoints use offset/limit, default limit 100, max 100.
Responses include `_metadata.next` (a fully-qualified URL) when more pages exist.

Rate limits: see `throttle.py`. The client wires the throttle into every
request and retries 429s up to 3 times honoring `Retry-After`.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

from fub_api.auth import BasicAuthCredentials
from fub_api.exceptions import FUBAPIError, FUBAuthError, FUBRateLimitError
from fub_api.resources.calls import Calls
from fub_api.resources.deals import Deals
from fub_api.resources.events import Events
from fub_api.resources.notes import Notes
from fub_api.resources.people import People
from fub_api.resources.pipelines import Pipelines
from fub_api.resources.stages import Stages
from fub_api.resources.tasks import Tasks
from fub_api.resources.users import Users
from fub_api.throttle import Throttle

DEFAULT_BASE_URL = "https://api.followupboss.com/v1"

_MAX_429_RETRIES = 3
_DEFAULT_RETRY_AFTER_S = 5.0


class FUBClient:
    def __init__(
        self,
        credentials: BasicAuthCredentials,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        throttle: Throttle | None = None,
    ):
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=timeout)
        self.throttle = throttle or Throttle()

        self.people = People(self)
        self.deals = Deals(self)
        self.events = Events(self)
        self.tasks = Tasks(self)
        self.notes = Notes(self)
        self.calls = Calls(self)
        self.users = Users(self)
        self.pipelines = Pipelines(self)
        self.stages = Stages(self)

    @classmethod
    def from_env(cls, *, dotenv_path: str | None = None) -> FUBClient:
        load_dotenv(dotenv_path)
        api_key = os.getenv("FUB_API_KEY", "").strip()
        if not api_key:
            raise FUBAuthError("FUB_API_KEY is empty in environment.")
        creds = BasicAuthCredentials(
            api_key=api_key,
            system=os.getenv("FUB_X_SYSTEM") or None,
            system_key=os.getenv("FUB_X_SYSTEM_KEY") or None,
        )
        base_url = os.getenv("FUB_BASE_URL", DEFAULT_BASE_URL)
        return cls(creds, base_url=base_url)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        # `path` may be a relative path ("/people") or a fully-qualified URL
        # (as returned in `_metadata.next`). Honor both.
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        headers = {
            "Accept": "application/json",
            **self.credentials.auth_header(),
        }

        attempt = 0
        while True:
            self.throttle.before_request()
            resp = self._http.request(method, url, params=params, json=json, headers=headers)
            self.throttle.observe(resp.headers)

            if resp.status_code == 429 and attempt < _MAX_429_RETRIES:
                retry_after = _retry_after_seconds(resp) or _DEFAULT_RETRY_AFTER_S
                attempt += 1
                time.sleep(retry_after)
                continue

            return self._handle_response(resp)

    def _handle_response(self, resp: httpx.Response) -> Any:
        if resp.status_code == 401:
            raise FUBAuthError("Unauthorized", status_code=401, payload=_safe_json(resp))
        if resp.status_code == 429:
            raise FUBRateLimitError(
                "Rate limited (retries exhausted)",
                retry_after=_retry_after_seconds(resp),
                status_code=429,
                payload=_safe_json(resp),
            )
        if resp.status_code >= 400:
            raise FUBAPIError(
                f"FUB API error {resp.status_code}",
                status_code=resp.status_code,
                payload=_safe_json(resp),
            )
        if not resp.content:
            return None
        return resp.json()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FUBClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}
