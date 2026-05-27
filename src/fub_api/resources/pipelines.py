"""Pipelines resource (deal pipeline definitions). Each carries a nested
`stages[]` array — captured as a count + in RawJson; the authoritative
per-stage rows come from the Stages resource."""
from __future__ import annotations

from fub_api.resources._base import Resource


class Pipelines(Resource):
    PATH = "/pipelines"
    COLLECTION = "pipelines"
    DEFAULT_FIELDS = None
