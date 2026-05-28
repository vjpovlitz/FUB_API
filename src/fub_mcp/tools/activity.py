"""Per-agent activity tools over fub.Calls and fub.Notes."""
from __future__ import annotations

from .base import curated, default_window, md, resolve_users


@curated
def call_activity(
    user: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 20,
) -> str:
    """Call volume per agent over a date window (inbound/outbound, talk minutes).

    Use for "how many calls did X make this week", "call activity", "who's
    dialing the most". Optional `user` (name or UserId) filters to one agent;
    otherwise a leaderboard. `since`/`until` ISO dates (until EXCLUSIVE); default
    last 7 days. UserId = -1 is FUB's system/automated caller.
    """
    limit = max(1, min(limit, 100))
    s, u = default_window(since, until)
    where = ["COALESCE(c.StartedAtUtc, c.CreatedUtc) >= ?", "COALESCE(c.StartedAtUtc, c.CreatedUtc) < ?"]
    params: list = [limit, s, u]
    if user:
        matches = resolve_users(user)
        if not matches:
            return f"No agent matches {user!r}."
        if len(matches) > 1:
            return "Multiple agents match: " + ", ".join(f"{n} (id {i})" for i, n in matches)
        where.append("c.UserId = ?")
        params.append(int(matches[0][0]))
    sql = (
        "SELECT TOP (?) "
        "COALESCE(u.Name, CASE WHEN c.UserId = -1 THEN '(system/automated)' "
        "  ELSE CAST(c.UserId AS VARCHAR(20)) END) AS Agent, "
        "COUNT_BIG(*) AS Calls, "
        "SUM(CASE WHEN c.IsIncoming = 1 THEN 1 ELSE 0 END) AS Inbound, "
        "SUM(CASE WHEN c.IsIncoming = 0 THEN 1 ELSE 0 END) AS Outbound, "
        "SUM(ISNULL(c.Duration, 0)) / 60 AS TalkMinutes "
        "FROM fub.Calls c "
        "LEFT JOIN fub.Users u ON u.UserId = CAST(c.UserId AS VARCHAR(64)) "
        f"WHERE {' AND '.join(where)} "
        "GROUP BY c.UserId, u.Name ORDER BY Calls DESC"
    )
    return md(sql, params, cap=limit)


@curated
def note_activity(
    user: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 20,
) -> str:
    """Notes written per agent over a date window.

    Use for "how many notes did X write this week", "note-taking activity".
    Optional `user` (name or UserId) filters to one agent; otherwise a
    leaderboard. `since`/`until` ISO dates (until EXCLUSIVE); default last 7 days.
    CreatedById = -1 is FUB's system/automation actor.
    """
    limit = max(1, min(limit, 100))
    s, u = default_window(since, until)
    where = ["n.CreatedUtc >= ?", "n.CreatedUtc < ?"]
    params: list = [limit, s, u]
    if user:
        matches = resolve_users(user)
        if not matches:
            return f"No agent matches {user!r}."
        if len(matches) > 1:
            return "Multiple agents match: " + ", ".join(f"{n} (id {i})" for i, n in matches)
        where.append("n.CreatedById = ?")
        params.append(int(matches[0][0]))
    sql = (
        "SELECT TOP (?) "
        "COALESCE(u.Name, CASE WHEN n.CreatedById = -1 THEN '(system/automation)' "
        "  ELSE CAST(n.CreatedById AS VARCHAR(20)) END) AS Agent, "
        "COUNT_BIG(*) AS Notes "
        "FROM fub.Notes n "
        "LEFT JOIN fub.Users u ON u.UserId = CAST(n.CreatedById AS VARCHAR(64)) "
        f"WHERE {' AND '.join(where)} "
        "GROUP BY n.CreatedById, u.Name ORDER BY Notes DESC"
    )
    return md(sql, params, cap=limit)
