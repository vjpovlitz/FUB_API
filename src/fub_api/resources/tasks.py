"""Tasks resource (activity fact). FK: personId, assignedUserId, createdById."""
from __future__ import annotations

from fub_api.resources._base import Resource


class Tasks(Resource):
    PATH = "/tasks"
    COLLECTION = "tasks"
    DEFAULT_FIELDS = None
