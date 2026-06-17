"""Task tools over fub.Tasks (set / completed / missed per agent)."""
from __future__ import annotations

from .base import curated, default_window, md, resolve_users


@curated
def task_summary(user: str, since: str | None = None, until: str | None = None) -> str:
    """An agent's tasks SET vs CHECKED (completed) vs MISSED over a date window.

    Use for "how many tasks did X set / complete / miss this week". `user` is an
    agent name or UserId. `since`/`until` are ISO dates 'YYYY-MM-DD' (until is
    EXCLUSIVE); defaults to the last 7 days. Definitions:
      - Set       = tasks the agent authored/last-touched in the window (UpdatedById)
      - Completed = tasks ASSIGNED to the agent and marked done in the window
      - Missed    = tasks ASSIGNED to the agent, due in the window, past due, not done
    For a calendar week pass since=Monday and until=the following Monday.
    """
    matches = resolve_users(user)
    if not matches:
        return f"No agent matches {user!r}. Call agent_leaderboard or describe_table('Users') to see names."
    if len(matches) > 1:
        names = ", ".join(f"{n} (id {i})" for i, n in matches)
        return f"Multiple agents match {user!r}: {names}. Be more specific."
    uid, name = matches[0]
    s, u = default_window(since, until)
    uid_int = int(uid)
    sql = (
        'SELECT %s AS "Agent", '
        '(SELECT COUNT(*) FROM fub."Tasks" '
        ' WHERE "UpdatedById" = %s AND "UpdatedUtc" >= %s AND "UpdatedUtc" < %s) AS "TasksSet", '
        '(SELECT COUNT(*) FROM fub."Tasks" '
        ' WHERE "AssignedUserId" = %s AND "IsCompleted" = true '
        '   AND "CompletedUtc" >= %s AND "CompletedUtc" < %s) AS "TasksCompleted", '
        '(SELECT COUNT(*) FROM fub."Tasks" '
        ' WHERE "AssignedUserId" = %s AND "IsCompleted" = false AND "DueDate" IS NOT NULL '
        '   AND "DueDate" < (now() AT TIME ZONE \'utc\')::date '
        '   AND "DueDate" >= %s AND "DueDate" < %s) AS "TasksMissed"'
    )
    params = [name, uid_int, s, u, uid_int, s, u, uid_int, s, u]
    out = md(sql, params, cap=1)
    return out + f"\n\n_Window: {s} to {u} (exclusive, UTC). Missed = assigned, past-due, not completed._"
