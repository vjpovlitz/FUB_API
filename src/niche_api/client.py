"""Niche Data customers API client.

Auth: `Authorization: Bearer <publicId>.<secret>` (single token string).
Base: https://customers-api.nichedata.ai
Backend looks like Symfony API Platform (filter syntax `field[after]`,
`order[field]=asc`), so list responses are JSON-LD/Hydra collections with
`hydra:member` + `hydra:totalItems` + `hydra:view.hydra:next`. The paginator
(resources/_base.py) handles Hydra, plain arrays, and page-increment fallback.

Rate limits: 429 -> retry up to 3x honoring Retry-After.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

from niche_api.exceptions import NicheAPIError, NicheAuthError, NicheRateLimitError
from niche_api.resources.notices import Notices

DEFAULT_BASE_URL = "https://customers-api.nichedata.ai"

_MAX_429_RETRIES = 3
_DEFAULT_RETRY_AFTER_S = 5.0
# Pagination spans many requests over a long push; a transient read/connect
# timeout must retry, not crash the whole run.
_MAX_TRANSIENT_RETRIES = 5


class NicheClient:
    def __init__(self, token: str, *, base_url: str = DEFAULT_BASE_URL, timeout: float = 60.0):
        if not token or "." not in token:
            raise NicheAuthError("Niche token missing or malformed (expected '<publicId>.<secret>').")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=timeout)

        self.notices = Notices(self)

    @classmethod
    def from_env(cls, *, dotenv_path: str | None = None) -> NicheClient:
        load_dotenv(dotenv_path)
        token = os.getenv("NICHE_DATA_TOKEN", "").strip()
        if not token:
            raise NicheAuthError("NICHE_DATA_TOKEN is empty in environment.")
        base_url = os.getenv("NICHE_BASE_URL", DEFAULT_BASE_URL)
        return cls(token, base_url=base_url)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        # `path` may be relative ("/notices") or a fully-qualified URL (as
        # returned in hydra:view.hydra:next). Honor both.
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        # The backend is a JSON:API server (application/vnd.api+json). It returns
        # 406 for application/ld+json or application/json — it ONLY negotiates
        # vnd.api+json (or */*). Records come back as {id, type, attributes:{...}}.
        headers = {
            "Accept": "application/vnd.api+json",
            "Authorization": f"Bearer {self.token}",
        }

        attempt = 0
        transient = 0
        while True:
            try:
                resp = self._http.request(method, url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if transient >= _MAX_TRANSIENT_RETRIES:
                    raise NicheAPIError(f"Transient network error after retries: {exc}") from exc
                transient += 1
                time.sleep(min(2 ** transient, 30))
                continue
            if resp.status_code == 429 and attempt < _MAX_429_RETRIES:
                attempt += 1
                time.sleep(_retry_after_seconds(resp) or _DEFAULT_RETRY_AFTER_S)
                continue
            return self._handle_response(resp)

    def _handle_response(self, resp: httpx.Response) -> Any:
        if resp.status_code in (401, 403):
            raise NicheAuthError(
                "Unauthorized" if resp.status_code == 401 else "Forbidden (token revoked/expired)",
                status_code=resp.status_code,
                payload=_safe_json(resp),
            )
        if resp.status_code == 429:
            raise NicheRateLimitError(
                "Rate limited (retries exhausted)",
                retry_after=_retry_after_seconds(resp),
                status_code=429,
                payload=_safe_json(resp),
            )
        if resp.status_code >= 400:
            raise NicheAPIError(
                f"Niche API error {resp.status_code}",
                status_code=resp.status_code,
                payload=_safe_json(resp),
            )
        if not resp.content:
            return None
        return resp.json()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> NicheClient:
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
        return {"raw": resp.text[:500]}
