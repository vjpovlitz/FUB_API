"""Calls resource (activity fact, high volume ~57k). FK: personId, userId.

userId can be -1 (FUB system/automated call) — captured but not FK-enforced.
"""
from __future__ import annotations

from fub_api.resources._base import Resource


class Calls(Resource):
    PATH = "/calls"
    COLLECTION = "calls"
    DEFAULT_FIELDS = None
