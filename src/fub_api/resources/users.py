"""Users resource (team members). Small, slow-changing dimension."""
from __future__ import annotations

from fub_api.resources._base import Resource


class Users(Resource):
    PATH = "/users"
    COLLECTION = "users"
    DEFAULT_FIELDS = None
