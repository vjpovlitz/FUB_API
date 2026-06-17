"""Deal-detail tool over fub.Deals."""
from __future__ import annotations

from .base import curated, md


@curated
def deal_detail(deal_id: str) -> str:
    """Full detail for one deal: stage, value, linked people & agents, key dates.

    Use for "show me deal N", "details of deal X". `deal_id` is the DealId (PK).
    IsClosedStage comes from the deal's stage (FUB has no won/lost status).
    """
    sql = (
        'SELECT d."DealId", d."Name", d."Status", d."Price", d."PipelineName", '
        'd."StageName", s."IsClosedStage", d."PersonNames", d."UserNames", '
        'd."ProjectedCloseDate", d."CustomClosingDate", d."EnteredStageUtc" '
        'FROM fub."Deals" d '
        'LEFT JOIN fub.vw_dealsbystage s ON s."StageId" = d."StageId" '
        'WHERE d."DealId" = %s LIMIT 1'
    )
    return md(sql, [deal_id], cap=1)
