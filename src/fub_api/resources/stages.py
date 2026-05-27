"""Stages resource. Mixes person stages (pipelineId=null, e.g. "Lead") and
deal-pipeline stages (pipelineId set). `peopleCount` is a live snapshot."""
from __future__ import annotations

from fub_api.resources._base import Resource


class Stages(Resource):
    PATH = "/stages"
    COLLECTION = "stages"
    DEFAULT_FIELDS = None
