"""Exception hierarchy for FUB API errors."""
from __future__ import annotations

from typing import Any


class FUBAPIError(Exception):
    """Generic FUB API error (4xx/5xx not otherwise classified)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class FUBAuthError(FUBAPIError):
    """401 Unauthorized — bad API key or missing credentials."""


class FUBRateLimitError(FUBAPIError):
    """429 Too Many Requests — burst or daily cap exhausted after retries."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ):
        super().__init__(message, status_code=status_code, payload=payload)
        self.retry_after = retry_after
