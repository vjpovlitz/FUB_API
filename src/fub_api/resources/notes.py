"""Notes resource (activity fact). FK: personId, createdById."""
from __future__ import annotations

from fub_api.resources._base import Resource


class Notes(Resource):
    PATH = "/notes"
    COLLECTION = "notes"
    DEFAULT_FIELDS = None
