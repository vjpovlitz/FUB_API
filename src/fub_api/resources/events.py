"""Events resource. Rate-limited to 10/window (vs 125) — throttle handles pacing."""
from __future__ import annotations

from fub_api.resources._base import Resource


class Events(Resource):
    PATH = "/events"
    COLLECTION = "events"
    DEFAULT_FIELDS = None
