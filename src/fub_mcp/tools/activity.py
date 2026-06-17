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
    where = [
        'COALESCE(c."StartedAtUtc", c."UpdatedUtc") >= %s',
        'COALESCE(c."StartedAtUtc", c."UpdatedUtc") < %s',
    ]
    params: list = [s, u]
    if user:
        matches = resolve_users(user)
        if not matches:
            return f"No agent matches {user!r}."
        if len(matches) > 1:
            return "Multiple agents match: " + ", ".join(f"{n} (id {i})" for i, n in matches)
        where.append('c."UserId" = %s')
        params.append(int(matches[0][0]))
    params.append(limit)  # LIMIT is the LAST placeholder
    sql = (
        'SELECT '
        'COALESCE(u."Name", CASE WHEN c."UserId" = -1 THEN \'(system/automated)\' '
        '  ELSE c."UserId"::text END) AS "Agent", '
        'COUNT(*) AS "Calls", '
        'SUM(CASE WHEN c."IsIncoming" = true THEN 1 ELSE 0 END) AS "Inbound", '
        'SUM(CASE WHEN c."IsIncoming" = false THEN 1 ELSE 0 END) AS "Outbound", '
        'SUM(COALESCE(c."Duration", 0)) / 60 AS "TalkMinutes" '
        'FROM fub."Calls" c '
        'LEFT JOIN fub."Users" u ON u."UserId" = c."UserId"::text '
        f'WHERE {" AND ".join(where)} '
        'GROUP BY c."UserId", u."Name" ORDER BY "Calls" DESC LIMIT %s'
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
    Attribution is by UpdatedById (the note's author/last editor); UpdatedById =
    -1 is FUB's system/automation actor.
    """
    limit = max(1, min(limit, 100))
    s, u = default_window(since, until)
    where = ['n."UpdatedUtc" >= %s', 'n."UpdatedUtc" < %s']
    params: list = [s, u]
    if user:
        matches = resolve_users(user)
        if not matches:
            return f"No agent matches {user!r}."
        if len(matches) > 1:
            return "Multiple agents match: " + ", ".join(f"{n} (id {i})" for i, n in matches)
        where.append('n."UpdatedById" = %s')
        params.append(int(matches[0][0]))
    params.append(limit)  # LIMIT is the LAST placeholder
    sql = (
        'SELECT '
        'COALESCE(u."Name", CASE WHEN n."UpdatedById" = -1 THEN \'(system/automation)\' '
        '  ELSE n."UpdatedById"::text END) AS "Agent", '
        'COUNT(*) AS "Notes" '
        'FROM fub."Notes" n '
        'LEFT JOIN fub."Users" u ON u."UserId" = n."UpdatedById"::text '
        f'WHERE {" AND ".join(where)} '
        'GROUP BY n."UpdatedById", u."Name" ORDER BY "Notes" DESC LIMIT %s'
    )
    return md(sql, params, cap=limit)
