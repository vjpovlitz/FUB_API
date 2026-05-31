"""Seed a self-contained demo warehouse with SYNTHETIC, non-PII data.

The unified dashboard reads only the vendor-neutral `analytics.*` views, so the
demo skips the entire ETL/base-table chain and writes synthetic rows straight
into the five analytics objects (created here as plain tables — the dashboard
queries them identically whether they're tables or views).

Everything is fake: names from fixed lists, emails @example.com, random dates.
No real Follow Up Boss / GoHighLevel data is ever touched. Idempotent: drops +
recreates the demo tables on each run. Deterministic (fixed RNG seed).

Run (inside the demo compose network):
    python demo/seed_demo.py

Connection comes from the same env vars the app uses (GHL_SQL_*), pointed at the
bundled `sqlserver` service.
"""
from __future__ import annotations

import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import pyodbc

RNG = random.Random(20260531)  # deterministic demo data

# --- connection ---------------------------------------------------------------
SERVER = os.getenv("GHL_SQL_SERVER", "sqlserver,1433")
USER = os.getenv("GHL_SQL_USER", "sa")
PW = os.getenv("GHL_SQL_PASSWORD", "Demo_Passw0rd!")
DB = os.getenv("GHL_SQL_DATABASE", "dcr_demo")


def _conn_str(database: str) -> str:
    return (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SERVER};"
        f"UID={USER};PWD={PW};DATABASE={database};"
        f"TrustServerCertificate=yes;Encrypt=no;"
    )


def connect_with_retry(database: str, timeout_s: int = 150) -> pyodbc.Connection:
    """Wait for SQL Server to accept connections (container takes a while to boot)."""
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            cn = pyodbc.connect(_conn_str(database), autocommit=True, timeout=5)
            print(f"  connected to [{database}]", flush=True)
            return cn
        except pyodbc.Error as e:  # noqa: PERF203
            last = e
            print("  waiting for SQL Server…", flush=True)
            time.sleep(4)
    raise SystemExit(f"could not connect to SQL Server in {timeout_s}s: {last}")


# --- reference data (all synthetic) -------------------------------------------
SYSTEMS = ["FollowUpBoss", "GoHighLevel"]
SOURCES = ["Zillow", "Realtor.com", "Website", "Referral", "Facebook Ads",
           "Google Ads", "Open House", "Cold Call", "Import"]
FIRST = ["Avery", "Jordan", "Riley", "Casey", "Morgan", "Taylor", "Quinn", "Skyler",
         "Drew", "Reese", "Cameron", "Hayden", "Parker", "Rowan", "Sage", "Emerson",
         "Marisol", "Devon", "Noor", "Kai", "Luca", "Mateo", "Priya", "Elena"]
LAST = ["Nguyen", "Patel", "Garcia", "Smith", "Johnson", "Khan", "Rossi", "Kim",
        "Brown", "Martinez", "Lee", "Walker", "Hughes", "Adams", "Flores", "Reed"]

# agents per system: (UserId, Name, Role)
AGENTS = {
    "FollowUpBoss": [(f"F{i}", f"{FIRST[i]} {LAST[i]}",
                      "Agent" if i else "Broker") for i in range(4)],
    "GoHighLevel": [(f"G{i}", f"{FIRST[i + 6]} {LAST[i + 2]}",
                     "Agent" if i else "Manager") for i in range(6)],
}

FUB_STAGES = ["New Lead", "Qualified", "Showing", "Under Contract", "Closed"]
GHL_STAGES = ["New", "Contacted", "Appointment", "Negotiation", "Won"]
FUB_PIPE, GHL_PIPE = "Buyer Pipeline", "Seller Pipeline"
ACTIVITY_FUB = ["Call", "Note", "Task", "Event"]
ACTIVITY_GHL = ["Message", "Appointment"]
CALL_OUTCOMES = ["Connected", "No Answer", "Left Voicemail", "Busy", "Wrong Number"]
TASK_STATUS = ["Completed", "Open", "Missed"]

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _name() -> str:
    return f"{RNG.choice(FIRST)} {RNG.choice(LAST)}"


def _rand_dt(days_back: int) -> datetime:
    return NOW - timedelta(days=RNG.randint(0, days_back),
                           hours=RNG.randint(0, 23), minutes=RNG.randint(0, 59))


# --- schema -------------------------------------------------------------------
DDL = {
    "vw_AllContacts": """
        ContactId VARCHAR(64), SourceSystem VARCHAR(32), FullName NVARCHAR(256),
        Email NVARCHAR(256), Phone VARCHAR(64), Source NVARCHAR(128),
        DateAddedUtc DATETIME2(3)""",
    "vw_LeadFunnel": """
        LeadDate DATE, LeadSource NVARCHAR(128), SourceSystem VARCHAR(32),
        LeadsCreated BIGINT, EngagedContacts BIGINT, OppsCreated BIGINT,
        OppsWon BIGINT, EngagedPct DECIMAL(5,1)""",
    "vw_AgentLeaderboard": """
        SourceSystem VARCHAR(32), UserId VARCHAR(64), AgentName NVARCHAR(256),
        Role NVARCHAR(64), LeadsAssigned BIGINT, LeadsLast7 INT, LeadsLast30 INT,
        ActivityCount BIGINT, DealsTotal BIGINT, DealsWon INT,
        PipelineValueOpen DECIMAL(18,2), PipelineValueWon DECIMAL(18,2)""",
    "vw_Opportunities": """
        OpportunityId VARCHAR(64), SourceSystem VARCHAR(32), Name NVARCHAR(256),
        Pipeline NVARCHAR(128), Stage NVARCHAR(128), Status VARCHAR(16),
        Value DECIMAL(18,2), AssignedUserId VARCHAR(64), AssignedAgent NVARCHAR(256),
        CreatedUtc DATETIME2(3), ClosedUtc DATETIME2(3)""",
    "vw_Activity": """
        ActivityId VARCHAR(64), SourceSystem VARCHAR(32), ActivityType VARCHAR(24),
        Direction VARCHAR(16), PersonId VARCHAR(64), UserId VARCHAR(64),
        AgentName NVARCHAR(256), Outcome NVARCHAR(64), DurationSec INT,
        OccurredUtc DATETIME2(3)""",
}


def ensure_database(cur) -> None:
    cur.execute(f"IF DB_ID('{DB}') IS NULL CREATE DATABASE [{DB}]")


def build_schema(cur) -> None:
    cur.execute("IF SCHEMA_ID('analytics') IS NULL EXEC('CREATE SCHEMA analytics')")
    for name, cols in DDL.items():
        cur.execute(f"IF OBJECT_ID('analytics.{name}','U') IS NOT NULL DROP TABLE analytics.{name}")
        cur.execute(f"CREATE TABLE analytics.{name} ({cols})")
    print("  schema ready (analytics.* demo tables)", flush=True)


# --- data generation ----------------------------------------------------------
def gen_contacts() -> list[tuple]:
    rows = []
    counts = {"FollowUpBoss": 1200, "GoHighLevel": 3000}
    for sysname, n in counts.items():
        for _ in range(n):
            nm = _name()
            email = nm.lower().replace(" ", ".") + f"{RNG.randint(1, 999)}@example.com"
            phone = f"(555) {RNG.randint(200, 999)}-{RNG.randint(1000, 9999)}"
            rows.append((str(uuid.uuid4())[:18], sysname, nm, email, phone,
                         RNG.choice(SOURCES), _rand_dt(365)))
    return rows


def gen_opportunities() -> list[tuple]:
    rows = []
    plan = {"FollowUpBoss": (FUB_PIPE, FUB_STAGES, 220),
            "GoHighLevel": (GHL_PIPE, GHL_STAGES, 420)}
    for sysname, (pipe, stages, n) in plan.items():
        agents = AGENTS[sysname]
        for _ in range(n):
            stage = RNG.choice(stages)
            won = stage == stages[-1]
            lost = (not won) and RNG.random() < 0.18
            status = "Won" if won else ("Lost" if lost else "Open")
            created = _rand_dt(300)
            closed = created + timedelta(days=RNG.randint(3, 90)) if status != "Open" else None
            # GHL monetary value is not tracked for this account (mirror reality)
            value = 0 if sysname == "GoHighLevel" else RNG.choice(
                [150_000, 225_000, 310_000, 420_000, 550_000, 680_000])
            uid, aname, _ = RNG.choice(agents)
            rows.append((str(uuid.uuid4())[:18], sysname,
                         f"{_name()} — {pipe.split()[0]}", pipe, stage, status,
                         value, uid, aname, created, closed))
    return rows


def gen_activity(contacts: list[tuple]) -> list[tuple]:
    rows = []
    for cid, sysname, *_rest in contacts:
        agents = AGENTS[sysname]
        types = ACTIVITY_FUB if sysname == "FollowUpBoss" else ACTIVITY_GHL
        for _ in range(RNG.randint(0, 6)):
            atype = RNG.choice(types)
            uid, aname, _ = RNG.choice(agents)
            direction, outcome, dur = "", "", 0
            if atype == "Call":
                direction = RNG.choice(["Inbound", "Outbound"])
                outcome = RNG.choice(CALL_OUTCOMES)
                dur = RNG.randint(0, 900)
            elif atype == "Task":
                outcome = RNG.choice(TASK_STATUS)
            elif atype == "Message":
                direction = RNG.choice(["Inbound", "Outbound"])
                outcome = RNG.choice(["SMS", "Email"])
            elif atype == "Appointment":
                outcome = RNG.choice(["Confirmed", "Showed", "No Show", "Cancelled"])
            elif atype == "Event":
                outcome = RNG.choice(["Property View", "Saved Search", "Email Open"])
            else:  # Note
                outcome = "Note"
            # messages/events aren't agent-attributed (mirror real data)
            if atype in ("Message", "Event"):
                uid, aname = "", None
            rows.append((str(uuid.uuid4())[:18], sysname, atype, direction, cid,
                         uid, aname, outcome, dur, _rand_dt(180)))
    return rows


def gen_funnel(contacts: list[tuple]) -> list[tuple]:
    """Aggregate contacts into a per (day, source, system) funnel with plausible drop-off."""
    buckets: dict[tuple, int] = {}
    for _cid, sysname, _nm, _em, _ph, src, dt in contacts:
        if (NOW - dt).days <= 120:
            buckets[(dt.date(), src, sysname)] = buckets.get((dt.date(), src, sysname), 0) + 1
    rows = []
    for (day, src, sysname), leads in buckets.items():
        engaged = int(leads * RNG.uniform(0.45, 0.8))
        opps = int(engaged * RNG.uniform(0.1, 0.3))
        won = int(opps * RNG.uniform(0.1, 0.4))
        eng_pct = round(engaged / leads * 100, 1) if leads else 0.0
        rows.append((day, src, sysname, leads, engaged, opps, won, eng_pct))
    return rows


def gen_leaderboard(contacts, opps, activity) -> list[tuple]:
    rows = []
    for sysname in SYSTEMS:
        sys_contacts = [c for c in contacts if c[1] == sysname]
        for uid, aname, role in AGENTS[sysname]:
            # assign a slice of leads to this agent deterministically
            assigned = [c for c in sys_contacts if RNG.random() < 1.0 / len(AGENTS[sysname])]
            last7 = sum(1 for c in assigned if (NOW - c[6]).days <= 7)
            last30 = sum(1 for c in assigned if (NOW - c[6]).days <= 30)
            acts = sum(1 for a in activity if a[5] == uid)
            my_opps = [o for o in opps if o[7] == uid]
            won = [o for o in my_opps if o[5] == "Won"]
            open_val = sum(o[6] for o in my_opps if o[5] == "Open")
            won_val = sum(o[6] for o in won)
            rows.append((sysname, uid, aname, role, len(assigned), last7, last30,
                         acts, len(my_opps), len(won), open_val, won_val))
    return rows


def insert(cur, table: str, ncols: int, rows: list[tuple]) -> None:
    if not rows:
        return
    cur.fast_executemany = True
    placeholders = ",".join(["?"] * ncols)
    cur.executemany(f"INSERT INTO analytics.{table} VALUES ({placeholders})", rows)
    print(f"  inserted {len(rows):>6,} into analytics.{table}", flush=True)


def main() -> int:
    print(f"Demo seed → {SERVER} / {DB}", flush=True)
    # 1. ensure DB exists (connect to master first)
    with connect_with_retry("master") as master:
        ensure_database(master.cursor())
    # 2. build schema + seed
    with connect_with_retry(DB) as cn:
        cur = cn.cursor()
        build_schema(cur)
        contacts = gen_contacts()
        opps = gen_opportunities()
        activity = gen_activity(contacts)
        funnel = gen_funnel(contacts)
        leaderboard = gen_leaderboard(contacts, opps, activity)

        insert(cur, "vw_AllContacts", 7, contacts)
        insert(cur, "vw_Opportunities", 11, opps)
        insert(cur, "vw_Activity", 10, activity)
        insert(cur, "vw_LeadFunnel", 8, funnel)
        insert(cur, "vw_AgentLeaderboard", 12, leaderboard)

        total = cur.execute("SELECT COUNT_BIG(*) FROM analytics.vw_AllContacts").fetchval()
        print(f"\n✓ demo seeded — {total:,} contacts across {len(SYSTEMS)} systems", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
