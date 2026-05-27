"""Deals resource. Custom fields come back inline; `allFields` 400s here."""
from __future__ import annotations

from fub_api.resources._base import Resource


class Deals(Resource):
    PATH = "/deals"
    COLLECTION = "deals"
    DEFAULT_FIELDS = None
