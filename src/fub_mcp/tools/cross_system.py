"""Cross-system tool over analytics.vw_AllContacts (GoHighLevel + Follow Up Boss)."""
from __future__ import annotations

from typing import Literal

from .base import curated, md


@curated
def cross_system_contacts(group_by: Literal["system", "source"] = "system", limit: int = 25) -> str:
    """Contacts across BOTH CRMs (GoHighLevel + Follow Up Boss), unioned.

    Use for "total contacts across both systems", "how many contacts in GHL vs
    FUB", "top lead sources across both CRMs". `group_by='system'` gives per-CRM
    counts with email/phone coverage; `group_by='source'` gives the top lead
    sources across both (limited by `limit`).
    """
    if group_by == "source":
        limit = max(1, min(limit, 200))
        sql = (
            "SELECT TOP (?) ISNULL(NULLIF(Source,''),'(unknown)') AS Source, "
            "COUNT_BIG(*) AS Contacts "
            "FROM analytics.vw_AllContacts "
            "GROUP BY ISNULL(NULLIF(Source,''),'(unknown)') "
            "ORDER BY Contacts DESC"
        )
        return md(sql, [limit], cap=limit)
    sql = (
        "SELECT SourceSystem, COUNT_BIG(*) AS Contacts, "
        "SUM(CASE WHEN COALESCE(Email,'') <> '' THEN 1 ELSE 0 END) AS WithEmail, "
        "SUM(CASE WHEN COALESCE(Phone,'') <> '' THEN 1 ELSE 0 END) AS WithPhone "
        "FROM analytics.vw_AllContacts "
        "GROUP BY SourceSystem ORDER BY Contacts DESC"
    )
    return md(sql, cap=10)
