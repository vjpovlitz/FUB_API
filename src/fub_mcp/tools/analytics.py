"""KPI tools backed by the fub.vw_* analytics views (deterministic rollups)."""
from __future__ import annotations

from typing import Literal, get_args

from ..db import MAX_ROWS_CEILING
from .base import check_choice, check_date, curated, md

AgentSort = Literal[
    "LeadsAssigned", "LeadsLast7", "LeadsLast30", "EventsTotal", "EventsLast7",
    "DealsTotal", "DealsClosed", "PipelineValueOpen", "PipelineValueClosed",
]


@curated
def agent_leaderboard(order_by: AgentSort = "LeadsAssigned", limit: int = 20) -> str:
    """Per-agent performance leaderboard (with agent names).

    Use for "top agents by X", "who owns the most leads", "who closed the most
    deals", "rep activity". Columns: leads assigned / last-7 / last-30, events
    total / last-7, deals total / closed, open & closed pipeline value. Sorted by
    `order_by` descending. (FUB has no won/lost — "closed" = a closed-stage deal.)
    """
    limit = max(1, min(limit, 100))
    order_by = check_choice(order_by, get_args(AgentSort), "order_by")
    sql = (
        'SELECT COALESCE(NULLIF(u."Name",\'\'), lb."UserId") AS "Agent", u."Role", '
        'lb."LeadsAssigned", lb."LeadsLast30", lb."EventsTotal", lb."DealsTotal", '
        'lb."DealsClosed", lb."PipelineValueOpen", lb."PipelineValueClosed" '
        'FROM fub.vw_agentleaderboard lb '
        'LEFT JOIN fub."Users" u ON u."UserId" = lb."UserId" '
        f'ORDER BY lb."{order_by}" DESC NULLS LAST LIMIT %s'
    )
    return md(sql, [limit], cap=limit)


@curated
def daily_lead_funnel(
    since: str | None = None,
    until: str | None = None,
    source: str | None = None,
    limit: int = 100,
) -> str:
    """Daily funnel (engaged contacts -> deals closed) with conversion percentages.

    Use for "lead funnel for last week", "daily conversion trend". `since`/`until`
    are ISO dates 'YYYY-MM-DD' (optional); `source` filters one lead source.
    "Engaged" = a person with >=1 event. Newest days first.
    """
    limit = max(1, min(limit, MAX_ROWS_CEILING))
    where = ["1 = 1"]
    params: list = []
    if since:
        where.append('"LeadDate" >= %s')
        params.append(check_date(since, "since"))
    if until:
        where.append('"LeadDate" <= %s')
        params.append(check_date(until, "until"))
    if source:
        where.append('"LeadSource" = %s')
        params.append(source)
    params.append(limit)  # LIMIT is the LAST placeholder
    sql = (
        'SELECT "LeadDate", "LeadSource", "EngagedContacts", "DealsClosed", '
        '"EngagedPct", "DealPct", "ClosedPct" '
        f'FROM fub.vw_dailyleadfunnel WHERE {" AND ".join(where)} '
        'ORDER BY "LeadDate" DESC, "EngagedContacts" DESC LIMIT %s'
    )
    return md(sql, params, cap=limit)


@curated
def deals_by_stage() -> str:
    """Deal pipeline broken down by stage: count, total & average value, closed flag.

    Use for "pipeline by stage", "how many deals are in each stage", "how many
    deals closed". Ordered by the stage's pipeline position. IsClosedStage = 1
    marks a closed stage (FUB has no won/lost status).
    """
    sql = (
        'SELECT "StageName", "IsClosedStage", "DealCount", "TotalValue", "AvgValue", "StageOrder" '
        'FROM fub.vw_dealsbystage ORDER BY "StageOrder"'
    )
    return md(sql, cap=100)


SourceSort = Literal["People", "ActivePeople"]


@curated
def lead_source_breakdown(order_by: SourceSort = "People", limit: int = 25, min_count: int = 0) -> str:
    """Lead volume by source: total people and active (non-Trash) people per source.

    Use for "where do our leads come from", "top lead sources", "which source has
    the most leads". `min_count` filters out tiny sources. Sorted by `order_by`
    descending. (Source is derived from the People records.)
    """
    limit = max(1, min(limit, 200))
    order_by = check_choice(order_by, get_args(SourceSort), "order_by")
    sql = (
        'SELECT COALESCE(NULLIF("Source",\'\'),\'(unknown)\') AS "Source", '
        'COUNT(*) AS "People", '
        'SUM(CASE WHEN "Stage" <> \'Trash\' THEN 1 ELSE 0 END) AS "ActivePeople" '
        'FROM fub."People" '
        'GROUP BY COALESCE(NULLIF("Source",\'\'),\'(unknown)\') '
        'HAVING COUNT(*) >= %s '
        f'ORDER BY "{order_by}" DESC LIMIT %s'
    )
    return md(sql, [max(0, min_count), limit], cap=limit)
