"""People resource. Custom fields require `?fields=allFields`."""
from __future__ import annotations

from fub_api.resources._base import Resource


class People(Resource):
    PATH = "/people"
    COLLECTION = "people"
    DEFAULT_FIELDS = "allFields"  # required to receive custom fields
    # The default list silently excludes stage="Trash" people (2,091 vs 3,318).
    # We want all raw data — trashed rows are still referenced by active deals.
    DEFAULT_PARAMS = {"includeTrash": "true"}
