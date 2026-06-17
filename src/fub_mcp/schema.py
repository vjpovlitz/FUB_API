"""Schema introspection + a DCR/FUB business glossary.

The glossary is the single most important context for the model: it explains what
the warehouse means (stages, the no-won/lost quirk, which view answers which
question) so the model picks the right tool or writes correct SQL instead of
guessing. Covers schema `fub` (Follow Up Boss) and `analytics` (cross-system).
"""
from __future__ import annotations

from .db import run_readonly

# Schemas this server is allowed to introspect / query.
SCHEMAS = ("fub", "analytics")

GLOSSARY = """\
# DCR warehouse — Follow Up Boss (PostgreSQL, schema `fub`)

CRM data for Dana Capital Realty, extracted from Follow Up Boss. All timestamps
are UTC (columns end in `Utc`). This connection is READ-ONLY. PostgreSQL dialect:
use `LIMIT n` (NOT `SELECT TOP`); date math via `now() AT TIME ZONE 'utc'` and
`interval`; case-insensitive match via `ILIKE`. Identifiers are case-sensitive
PascalCase, so DOUBLE-QUOTE them: `fub."People"."PersonId"`. The vw_* view NAMES
are lowercase (e.g. `fub.vw_agentleaderboard`) but their output columns stay
quoted PascalCase. Sister GoHighLevel data lives in schema `ghl`; the two CRMs are
unioned in `analytics.vw_allcontacts`.

## Facts
- `fub."People"` (~5,294) — leads/contacts. PersonId (PK), FirstName/LastName/Name,
  Emails/Phones (pipe-delimited) + PrimaryEmail/PrimaryPhone, Stage (lead stage),
  Source (lead source), AssignedUserId (owning agent; INTEGER -> join
  fub."Users"."UserId"::text), Tags (pipe-delimited), UpdatedUtc, LastActivityUtc,
  22 Custom* columns, RawJson. NOTE: no created timestamp. QUIRK: trashed leads are
  INCLUDED (Stage = 'Trash'); filter `"Stage" <> 'Trash'` for "active" people.
- `fub."Deals"` (~231) — transactions/opportunities. DealId (PK), Name, Status,
  Price, PipelineId/PipelineName, StageId (INT) / StageName, PrimaryPersonId +
  PersonIds/PersonNames (pipe-delimited; the funnel link), PrimaryUserId +
  UserIds/UserNames, EnteredStageUtc, ProjectedCloseDate, CustomClosingDate.
  QUIRK: FUB has NO won/lost status — a deal is "closed" when its StageId maps to a
  fub."Stages" row with ClosedStage = true (or fub.vw_dealsbystage.IsClosedStage = 1).
- `fub."Events"` (~3,261) — activity log: emails, calls, web visits, etc. EventId
  (PK), PersonId (FK), Type, OccurredUtc/UpdatedUtc. "Engaged" = a person with >=1 event.
- `fub."Tasks"` (~2,924) — to-dos. TaskId (PK), PersonId (FK), AssignedUserId +
  UpdatedById (FK -> Users; -1 = system/automation), IsCompleted (BOOLEAN; use
  `= true`), CompletedUtc, DueDate, UpdatedUtc. NOTE: no created timestamp —
  attribution is by UpdatedById/UpdatedUtc. Prefer the `task_summary` tool.
- `fub."Notes"` (~11,385) — free-text notes on contacts. NoteId (PK), PersonId (FK),
  Body, UpdatedBy/UpdatedById (FK -> Users; -1 = system), UpdatedUtc. No created ts.
- `fub."Calls"` (~58,690) — phone calls. CallId (PK), PersonId (FK), UserId (INTEGER
  FK -> Users; **-1 = system/automated**, no Users row), UserName, IsIncoming
  (BOOLEAN; use `= true`), Duration & RingDuration (seconds), Outcome, StartedAtUtc,
  UpdatedUtc. Prefer the `call_activity` tool for per-agent rollups.

## Dimensions
- `fub."Users"` (4) — agents/staff. UserId (PK, VARCHAR), Name, Email, Role.
  (Calls.UserId / Notes.UpdatedById are INTEGER -> cast to join: `u."UserId" = c."UserId"::text`.)
- `fub."Pipelines"` (2) — deal pipelines. PipelineId (PK), Name, StageCount, StageIds.
- `fub."Stages"` (20) — UNIFIED person + deal stages. StageId (PK), Name,
  StageKind ('Person'|'Deal'), PipelineId (null for person stages), ClosedStage
  (BOOLEAN; true = a closed deal stage), Color.
- `fub."Sources"` (27) — lead sources. DERIVED from People (Derived = true).
- `fub."Tags"` (34) — tags. PK is TagName (FUB tags have no id). DERIVED from People.

## Analytics views (schema `fub`, prefix `vw_`, lowercase names) — prefer for KPIs
- `vw_dailyleadfunnel` — per (LeadDate, LeadSource): EngagedContacts, DealsClosed,
  with EngagedPct/DealPct/ClosedPct.
- `vw_agentleaderboard` — per agent (UserId): LeadsAssigned, LeadsLast7/30,
  EventsTotal/Last7, DealsTotal/Closed, PipelineValueOpen/Closed.
- `vw_dealsbystage` — per stage: StageName, IsClosedStage (1/0), DealCount,
  TotalValue, AvgValue, StageOrder.

## Cross-system (schema `analytics`)
- `analytics.vw_allcontacts` (~257,579) — UNION ALL of ghl."Contacts" + fub."People",
  normalized: ContactId, SourceSystem ('GoHighLevel'|'FollowUpBoss'), FullName,
  Email, Phone, Source, DateAddedUtc. Use for "contacts across both CRMs".
"""


def _objects() -> dict[str, str]:
    """Map 'schema.name' -> 'BASE TABLE' | 'VIEW' for the allowed schemas."""
    placeholders = ", ".join("%s" for _ in SCHEMAS)
    cols, rows, _ = run_readonly(
        "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
        f"WHERE TABLE_SCHEMA IN ({placeholders}) ORDER BY TABLE_SCHEMA, TABLE_NAME",
        params=list(SCHEMAS),
        max_rows=500,
    )
    return {f"{r[0]}.{r[1]}": r[2] for r in rows}


def _split(name: str) -> tuple[str, str]:
    """Parse a (possibly schema-qualified) object name; default schema = fub."""
    bare = name.strip().strip('"').strip("[]")
    if "." in bare:
        schema, table = bare.split(".", 1)
        return schema.strip().strip('"').strip("[]"), table.strip().strip('"').strip("[]")
    return "fub", bare


def describe_schema() -> str:
    """Glossary + a compact list of every queryable table/view in fub + analytics."""
    objs = _objects()
    tables = [n for n, t in objs.items() if t == "BASE TABLE"]
    views = [n for n, t in objs.items() if t == "VIEW"]
    lines = [GLOSSARY, "\n## Queryable objects (call describe_table for columns)"]
    lines.append("Tables: " + ", ".join(tables))
    lines.append("Views:  " + ", ".join(views))
    return "\n".join(lines)


def describe_table(name: str) -> str:
    """Columns + types for one fub/analytics table or view (name validated)."""
    schema, table = _split(name)
    objs = _objects()
    key = f"{schema}.{table}"
    if key not in objs:
        avail = ", ".join(sorted(objs)) or "(none)"
        return f"Unknown object '{key}'. Available: {avail}"
    cols, rows, _ = run_readonly(
        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
        params=[schema, table],
        max_rows=500,
    )
    out = [f"{key} ({objs[key].lower()}) — {len(rows)} columns:"]
    for cname, dtype, nullable, maxlen in rows:
        t = f"{dtype}({maxlen})" if maxlen and maxlen > 0 else dtype
        null = "" if nullable == "YES" else " NOT NULL"
        out.append(f"  {cname}  {t}{null}")
    return "\n".join(out)
