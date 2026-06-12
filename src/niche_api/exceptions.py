"""Niche Data API exceptions (mirrors fub_api.exceptions)."""
from __future__ import annotations


class NicheAPIError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class NicheAuthError(NicheAPIError):
    """401 (invalid/missing token) or 403 (revoked/expired)."""


class NicheRateLimitError(NicheAPIError):
    """429 after retries are exhausted."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
