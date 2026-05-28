"""Record-lookup tools over fub.People and fub.Events."""
from __future__ import annotations

from .base import curated, md


@curated
def people_search(
    query: str | None = None,
    stage: str | None = None,
    source: str | None = None,
    include_trash: bool = False,
    limit: int = 25,
) -> str:
    """Find leads/contacts by name, email, or phone, with optional filters.

    Use for "find the lead named X", "look up john@email.com", "leads in stage Y",
    "leads from source Z". `query` matches name/email/phone (substring). `stage`
    and `source` are exact filters. Trashed leads are excluded unless
    `include_trash=True`. Most-recently-active first.
    """
    limit = max(1, min(limit, 200))
    where: list[str] = []
    params: list = [limit]
    if not include_trash:
        where.append("Stage <> 'Trash'")
    if query:
        where.append("(Name LIKE ? OR PrimaryEmail LIKE ? OR PrimaryPhone LIKE ?)")
        like = f"%{query}%"
        params += [like, like, like]
    if stage:
        where.append("Stage = ?")
        params.append(stage)
    if source:
        where.append("Source = ?")
        params.append(source)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT TOP (?) PersonId, Name, PrimaryEmail, PrimaryPhone, Stage, Source, "
        "AssignedTo, CreatedUtc, LastActivityUtc "
        f"FROM fub.People{clause} "
        "ORDER BY LastActivityUtc DESC"
    )
    return md(sql, params, cap=limit)


@curated
def event_activity(
    person_id: str | None = None,
    type: str | None = None,
    limit: int = 25,
) -> str:
    """Recent activity events (calls, emails, web visits, etc.), newest first.

    Use for "recent activity", "what happened with person N", "show calls/emails".
    `person_id` filters to one contact's timeline; `type` filters an event type
    (e.g. 'Call', 'Email', 'Visited Website'). Message is truncated.
    """
    limit = max(1, min(limit, 200))
    where: list[str] = []
    params: list = [limit]
    if person_id:
        where.append("PersonId = ?")
        params.append(person_id)
    if type:
        where.append("Type = ?")
        params.append(type)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT TOP (?) EventId, PersonId, Type, Source, "
        "COALESCE(OccurredUtc, CreatedUtc) AS WhenUtc, LEFT(Message, 80) AS Message "
        f"FROM fub.Events{clause} "
        "ORDER BY COALESCE(OccurredUtc, CreatedUtc) DESC"
    )
    return md(sql, params, cap=limit)
