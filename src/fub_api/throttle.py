"""Adaptive throttle for the Follow Up Boss API.

FUB returns standard X-RateLimit-* headers on every response:

    X-RateLimit-Limit          requests allowed in the current window
    X-RateLimit-Remaining      requests left in the current window
    X-RateLimit-Reset          seconds until the window resets (or epoch sec)

Like the GHL throttle, this watches headers and pads the inter-request gap
when remaining gets low. The exact burst/window values vary by FUB plan, so
this code adapts from what the server reports rather than hard-coding limits.

Usage:
    throttle = Throttle()
    throttle.before_request()
    resp = http.get(...)
    throttle.observe(resp.headers)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Mapping


# Polite floor — never exceed this sustained rate even if the server says we can.
_MIN_INTERVAL_S = 0.15  # ~6-7 RPS ceiling

# When remaining drops below this many requests, start padding the interval.
_LOW_WATER = 25

# FUB rate-limit windows are ~10s. `X-RateLimit-Reset` isn't returned on 200s,
# so we assume this window to derive a sustained pace from the per-endpoint
# `X-RateLimit-Limit`. This is what keeps the 10/window Events endpoint at
# ~1 req/sec automatically, while People/Deals (limit 125) stay at the floor.
_ASSUMED_WINDOW_S = 10.0


@dataclass
class Throttle:
    burst_remaining: int | None = None
    burst_limit: int | None = None
    burst_reset_s: float | None = None       # seconds until reset, if reported
    last_request_ts: float = 0.0
    sleeps_total_s: float = 0.0
    requests_total: int = 0
    _history: list[float] = field(default_factory=list)

    def observe(self, headers: Mapping[str, str]) -> None:
        """Update internal state from a response's rate-limit headers."""
        self.requests_total += 1
        rem = _get_int(headers, "X-RateLimit-Remaining")
        if rem is not None:
            self.burst_remaining = rem
        lim = _get_int(headers, "X-RateLimit-Limit")
        if lim is not None:
            self.burst_limit = lim
        reset = _get_int(headers, "X-RateLimit-Reset")
        if reset is not None:
            # FUB reports seconds-until-reset (small number). Some APIs report
            # an epoch second (large number). Treat anything > 10^9 as epoch.
            if reset > 1_000_000_000:
                self.burst_reset_s = max(0.0, reset - time.time())
            else:
                self.burst_reset_s = float(reset)

    def before_request(self) -> float:
        """Sleep enough to stay polite. Returns seconds slept."""
        now = time.monotonic()
        gap = now - self.last_request_ts if self.last_request_ts else 1e9
        wanted = self._wanted_interval()
        slept = 0.0
        if gap < wanted:
            slept = wanted - gap
            time.sleep(slept)
            self.sleeps_total_s += slept
        self.last_request_ts = time.monotonic()
        return slept

    def _wanted_interval(self) -> float:
        base = _MIN_INTERVAL_S

        # Sustained pace derived from the endpoint's own limit: spread `limit`
        # requests evenly across the assumed window. For Events (limit 10) this
        # is ~1.0s/req; for People/Deals (limit 125) it's below the floor.
        if self.burst_limit:
            base = max(base, _ASSUMED_WINDOW_S / max(self.burst_limit, 1))

        if self.burst_remaining is not None and self.burst_remaining <= 0:
            # We've eaten the window — wait for reset if known, else full window.
            return max(self.burst_reset_s or _ASSUMED_WINDOW_S, 1.0)

        if self.burst_remaining is not None and self.burst_remaining < _LOW_WATER:
            scarcity = (_LOW_WATER - self.burst_remaining) / _LOW_WATER
            ceiling = (self.burst_reset_s or _ASSUMED_WINDOW_S) / max(_LOW_WATER, 1)
            base = max(base, base + scarcity * ceiling)
        return base

    def stats(self) -> dict:
        return {
            "requests_total": self.requests_total,
            "sleeps_total_s": round(self.sleeps_total_s, 3),
            "burst_remaining": self.burst_remaining,
            "burst_limit": self.burst_limit,
            "burst_reset_s": self.burst_reset_s,
        }


def _get_int(headers: Mapping[str, str], key: str) -> int | None:
    raw = None
    if hasattr(headers, "get"):
        raw = headers.get(key) or headers.get(key.lower()) or headers.get(key.upper())
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None
