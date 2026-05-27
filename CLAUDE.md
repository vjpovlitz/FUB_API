# CLAUDE.md — FUB_API handoff

Project handoff for a fresh Claude Code session. Read this top-to-bottom before
making any changes. This is the **sister project** to GHL_API
(`/Users/smokestack/Projects/DCR/GHL_API`); same discipline, same patterns,
different vendor.

---

## 1. What this project is

Python client + ETL for the **Follow Up Boss (FUB) API**, extracting
CRM data into **SQL-Server-shaped CSVs** for a downstream warehouse load.

- **Owner:** vjpovlitz (Vinson Povlitz)
- **Vendor:** Follow Up Boss — `api.followupboss.com/v1`
- **Auth:** HTTP Basic — API key as username, empty password. Plus
  `X-System` / `X-System-Key` integration headers.
- **Working dir:** `/Users/smokestack/Projects/FUB_API`
- **Account:** redacted from public repo — see internal notes / `.env`.
- **Last worked:** 2026-05-27. All three core entities extracted + SQL load
  scripts generated. Next up: dimension tables + referential-integrity check
  (see §8).

### Why CSVs and not direct DB writes?

Same reason as GHL_API: customer wants the data in SQL Server. CSVs let us
decouple extract from load, keep the extract idempotent, and use `BULK INSERT`
for the load. A direct `pyodbc` path can be added later; CSV-first is on
purpose. Both feeds (GHL + FUB) land in the same warehouse with the same
column shape — that's why `DATA_RULES.md` is nearly identical.

---

## 2. Current state (all 3 core entities extracted + SQL prep, 2026-05-27)

What's done:

| Component | Status |
|---|---|
| Repo skeleton, `.env.example`, `.gitignore`, `pyproject.toml` | ✅ |
| `DATA_RULES.md` (canonical, mirrors GHL with `SourceSystem="FollowUpBoss"`) | ✅ |
| `src/fub_api/auth.py` — `BasicAuthCredentials` w/ X-System headers | ✅ |
| `src/fub_api/throttle.py` — adapts to `X-RateLimit-*` response headers | ✅ |
| `src/fub_api/client.py` — `FUBClient.from_env()`, 429 retry, throttle, `.people` | ✅ |
| `src/fub_api/exceptions.py` | ✅ |
| `scripts/smoke_test.py` — **green**: /identity, /people, /events, /deals all 200 | ✅ |
| `src/fub_api/sanitize.py` — ported verbatim from GHL (vendor-agnostic) | ✅ |
| `src/fub_api/resources/people.py` — `list` / `get` / `page` (next-cursor) | ✅ |
| `src/fub_api/mappers.py` — `PEOPLE_COLUMNS` (41 cols) + `map_person` | ✅ |
| `scripts/audit_csv.py` — ported; FUB PK map (People/Deals/Events) | ✅ |
| `scripts/export_people_poc.py` — extract + audit gate (any `--max-rows`) | ✅ |
| People custom fields (22 cols, `?fields=allFields`) + `RawJson` capture | ✅ |
| `src/fub_api/batch.py` — `Checkpoint` + `BatchExtractor` + `PeopleExtractor` | ✅ |
| Shared `resources/_base.py` paginator (People/Deals/Events) + `scripts/export.py` | ✅ |
| **Full People backfill — 3,318 rows (incl. Trash), 64 cols, 0 issues** | ✅ |
| **Full Deals backfill — 228 rows, 34 cols, 0 issues; funnel join 228/228** | ✅ |
| **Full Events backfill — 3,207 rows, 20 cols, 0 issues; join 3,207/3,207** | ✅ |
| Throttle paces from per-endpoint `burst_limit` (Events 10/win → ~1 req/s) | ✅ |
| `src/fub_api/schema.py` — SQL type overlay, validated vs mapper columns | ✅ |
| `scripts/generate_ddl.py` → `sql/create_tables.sql` / `staging_tables.sql` / `load_bulk_insert.sql` | ✅ |
| `src/fub_api/manifest.py` + `scripts/manifest.py` → `data/exports/manifest.json` | ✅ |
| **Dimension tables — Users (4), Pipelines (2), Stages (20), Sources (27), Tags (32)** | ✅ |
| Tests: 58 pass (23 sanitize + 19 schema/mapper sync + 16 integrity) | ✅ |

### Dimension tables (added 2026-05-27)

Five small dims that resolve the FK ids already in the facts. All audited 0
issues; every fact FK resolves 100% (People.StageId/SourceId/AssignedUserId/Tags;
Deals.PipelineId/StageId/PrimaryUserId).

| Dim | Source | Rows | Notes |
|---|---|---:|---|
| **Users** | `GET /users` | 4 | agents; flattens `picture`/`groups[]` |
| **Pipelines** | `GET /pipelines` | 2 | deal pipelines; nested `stages[]` → StageCount/StageIds |
| **Stages** | `/stages` ∪ `/pipelines[].stages[]` | 20 | **unified** — see gap below |
| **Sources** | DERIVED from People.csv | 27 | `/sources` 404, `/leadSources` 403 |
| **Tags** | DERIVED from People.csv | 32 | `/tags` 403; PK is TagName (FUB tags have no id) |

**Stages gap (important):** the standalone `GET /stages` returns ONLY person
stages (`pipelineId=null`). Deal-pipeline stages (ids 27,28,29,30,47,57) live
exclusively inside `GET /pipelines[].stages[]` — a person-only Stages table
orphans every `Deals.StageId`. `scripts/build_stages.py` unions both (disjoint
id ranges; `StageKind` = Person|Deal). Same class of hidden filter as People's
Trash (§5).

**Sources/Tags are DERIVED, not live.** The current API key is non-owner-scoped:
`/tags` and `/leadSources` return **403**, `/sources` is **404**. Both dims are
built by distinct-ing People.csv (`scripts/derive_dims.py`), with `Derived="1"`
so they can be re-pulled authoritatively once an owner-scoped key + `X-System-Key`
are registered (the standing founder ask). Don't block on it.

People design notes:
- `PEOPLE_COLUMNS` = 41 base + 22 `Custom*` + `RawJson` = **64 columns**.
- Custom fields require `?fields=allFields`; `People` resource defaults to it.
- `RawJson` = full sanitized person record (NVARCHAR(MAX)); it's the only
  >1000-char column (up to ~6.7k) and the audit flags it as informational,
  not an error. It's the safety net so no field is ever lost.
- `scripts/export.py --entity people` is the current runner (non-batched, per
  user: build batch but only use it when needed). `batch.py::PeopleExtractor`
  is ready for the sharded/resumable path but unused so far — the dataset is
  too small to need it. `export_people_poc.py` is the older People-only script,
  superseded by the generic `export.py`.

Funnel (verified 2026-05-27): 3,092 people have ≥1 event, 206 have a deal,
192 have both. Events join 100% to People; Deals join 100% to People.

### SQL Server load path (ready)

1. `sql/create_tables.sql` — typed `fub.*` tables (DROP+CREATE, PK on the
   `<Entity>Id`). Column order matches the CSV exactly.
2. `sql/staging_tables.sql` — `stg.*` tables, every column `NVARCHAR(MAX)` so
   BULK INSERT never type-fails.
3. `sql/load_bulk_insert.sql` — `BULK INSERT` each CSV into `stg.*`
   (FORMAT='CSV', CODEPAGE=65001, FIRSTROW=2, CRLF), then
   `INSERT..SELECT TRY_CONVERT(type, NULLIF(col,''))` into `fub.*`. Empties →
   NULL; bad values → NULL (not a failed load). Requires SQL Server 2017+.
   Set the data dir via sqlcmd `-v DataDir=...`.
4. Reconcile: the COUNT(*) queries at the end of the load script must match
   `rows` in `data/exports/manifest.json` (`scripts/manifest.py`).

Regenerate all SQL after any mapper/schema change: `python scripts/generate_ddl.py`.
The schema is validated against the mapper columns (`schema.validate()`), and a
test enforces it — drift is a hard error.

What's NOT done yet (next milestones — see §8):
- Small dims: users, pipelines, stages, sources, tags (labels for joins)
- Funnel POC script (formalize the People → Events → Deals reconcile above)
- Incremental/delta sync (currently full backfill only)

---

## 3. Critical files cheat sheet

```
FUB_API/
├── CLAUDE.md                          ← this file
├── DATA_RULES.md                      ← canonical data rules; code enforces
├── README.md                          ← user-facing setup
├── .env                               ← LIVE credentials, gitignored (key works)
├── .env.example                       ← template, committed
├── pyproject.toml                     ← deps: httpx, pydantic, dotenv, pytest
│
├── src/fub_api/
│   ├── auth.py                        ← BasicAuthCredentials + X-System hdrs
│   ├── client.py                      ← FUBClient.from_env(); .people .deals .events
│   ├── exceptions.py                  ← FUBAPIError / FUBAuthError / FUBRateLimitError
│   ├── throttle.py                    ← adaptive; paces from per-endpoint burst_limit
│   ├── sanitize.py                    ← ported from GHL (verbatim, vendor-agnostic)
│   ├── mappers.py                     ← *_COLUMNS + map_* (3 facts + 5 dims)
│   │                                     + CUSTOM_FIELD_TYPES (People, 22 fields)
│   ├── schema.py                      ← SQL type overlay; validate() vs mappers (8 tables)
│   ├── manifest.py                    ← row count + sha256 + schema fingerprint
│   ├── batch.py                       ← Checkpoint + BatchExtractor + PeopleExtractor
│   └── resources/
│       ├── _base.py                   ← shared next-cursor paginator
│       ├── people.py                  ← DEFAULT_FIELDS=allFields, includeTrash=true
│       ├── deals.py                   ← custom fields inline (allFields 400s)
│       ├── events.py                  ← rate-limited 10/window
│       ├── users.py                   ← dim: team members
│       ├── pipelines.py               ← dim: deal pipelines (nested stages[])
│       └── stages.py                  ← dim: person stages only (see build_stages.py)
│
├── scripts/
│   ├── smoke_test.py                  ← raw httpx auth check (read-only)
│   ├── export.py                      ← GENERIC single-endpoint extractor + audit (use this)
│   ├── build_stages.py                ← unified Stages = /stages ∪ /pipelines[].stages[]
│   ├── derive_dims.py                 ← Sources + Tags derived from People.csv (no live ep)
│   ├── check_integrity.py             ← FK gate: every fact FK resolves in its dim; exit=1
│   ├── export_people_poc.py           ← older People-only POC (superseded by export.py)
│   ├── audit_csv.py                   ← SQL-Server-safety audit; exit=1 on issue
│   ├── generate_ddl.py                ← writes the three sql/ files from schema.py
│   └── manifest.py                    ← writes data/exports/manifest.json
│
├── sql/                               ← generated; do not hand-edit
│   ├── create_tables.sql              ← typed fub.* (3 facts + 5 dims)
│   ├── staging_tables.sql             ← stg.* all NVARCHAR(MAX)
│   └── load_bulk_insert.sql           ← BULK INSERT + TRY_CONVERT cast + reconcile
│
├── tests/                             ← 58 pass: test_sanitize/test_schema/test_integrity
└── data/exports/                      ← OUTPUT, gitignored — CSVs + manifest land here
```

### How to run

```bash
# First-time setup (venv already exists at .venv/)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# .env already has a working FUB_API_KEY (fka_…). FUB_X_SYSTEM=DanaCapital-ETL.

# Smoke test (read-only) — confirms auth + prints rate-limit headers
.venv/bin/python scripts/smoke_test.py

# Extract a single-endpoint entity (paginates, maps, writes CSV, runs audit gate)
.venv/bin/python scripts/export.py --entity people     # 3,318 rows
.venv/bin/python scripts/export.py --entity deals      # 228
.venv/bin/python scripts/export.py --entity events     # 3,207 (~47s, 10/window)
.venv/bin/python scripts/export.py --entity users      # 4   (dim)
.venv/bin/python scripts/export.py --entity pipelines  # 2   (dim)
.venv/bin/python scripts/export.py --entity events --max-rows 50   # small test

# Stages dim — needs two endpoints (/stages ∪ /pipelines[].stages[]), own script
.venv/bin/python scripts/build_stages.py               # 20 (14 person + 6 deal)

# Sources + Tags dims — derived from People.csv (no live endpoint; run AFTER people)
.venv/bin/python scripts/derive_dims.py                # 27 sources, 32 tags

# Referential-integrity gate — every fact FK must resolve in its dim (run AFTER
# all extracts). Exit 1 on any orphan. 11 rules, currently 0 orphans.
.venv/bin/python scripts/check_integrity.py

# Re-audit existing CSVs without re-pulling
.venv/bin/python scripts/audit_csv.py

# Regenerate SQL after any mapper/schema change
.venv/bin/python scripts/generate_ddl.py

# Refresh the manifest (row counts + sha256)
.venv/bin/python scripts/manifest.py

# Tests (58 pass)
.venv/bin/python -m pytest tests/ -q
```

---

## 4. Data rules (canonical: `DATA_RULES.md`)

Short version — read the full doc for details:

1. **Naming:** `PascalCase`. PKs are `<Entity>Id`. FKs use the same name.
2. **Types:** ISO 8601 UTC for timestamps, `1`/`0` for `BIT`, pipe-delimited
   for arrays.
3. **Nulls:** empty string `""`. Never `"null"`, `"None"`, `"NaN"`.
4. **Audit columns on every row:** `SourceSystem="FollowUpBoss"`,
   `SourceSystemId`, `ExtractedAtUtc`.
5. **CSV format:** UTF-8 **with BOM**, **CRLF**, `csv.QUOTE_MINIMAL`, header
   row, one file per table.
6. **Sanitization:** every field through `fub_api.sanitize.*`. Newlines/tabs →
   space. Strip C0 controls. NFC normalize. Trim. Truncate to `max_len`.
7. **PII:** `data/exports/` is gitignored. Never commit a CSV. Mask in console.
8. **Idempotency:** re-running overwrites (backfill) or resumes from checkpoint
   (incremental).
9. **Resume:** atomic checkpoint after every page (`tmp + os.replace`); see §9.

---

## 5. API knowledge — what we expect (verify with smoke test)

### Auth

FUB uses **HTTP Basic** auth where the API key is the *username* and the
*password is empty*. The `Authorization` header value is:

```
Basic <base64("<api_key>:")>
```

Plus the integration identification headers (recommended on every request):

```
X-System: DanaCapital-ETL
X-System-Key: <UUID-if-registered>
```

`X-System-Key` is optional — the API will accept requests without it but
flags them as "unidentified" in FUB's internal logs.

### Base URL

`https://api.followupboss.com/v1`

### Pagination (VERIFIED 2026-05-27)

List endpoints page with a **`next` cursor token**, not offset:

- `?limit=N` — max **100**
- Response `_metadata`: `{ collection, offset, limit, total, next, nextLink }`
- `next` is an **opaque base64 token** (decodes to e.g. `{"sinceId":8140}`)
- `nextLink` is the fully-qualified URL for the next page
- `total` gives the full collection count up front (handy for progress)
- An **empty `people`/`events`/`deals` array marks the end** — treat that as
  done even if a stale `next` token is echoed back
- `FUBClient.request()` accepts both relative paths and full URLs, and
  `People.page()` passes the `next` token via the `next` query param
- `offset` exists but the cursor is the recommended path; prefer `next`

### Rate limits (VERIFIED — they differ per endpoint!)

`X-RateLimit-Limit` / `X-RateLimit-Remaining` come back on every response.
`X-RateLimit-Reset` and `Retry-After` were NOT present on 200s (expect Reset
near window exhaustion and Retry-After on 429s).

| Endpoint | `X-RateLimit-Limit` |
|---|---:|
| `/people` | **125** |
| `/deals` | **125** |
| `/events` | **10**  ← much tighter; pace Events carefully |

The throttle adapts from `Remaining`; for Events the floor matters far more.
Registering an `X-System-Key` reportedly raises the per-second allowance
(FUB nags about this in `_metadata.notice` when the key is unset).

### Verified volumes (2026-05-27)

| Entity | total | notes |
|---|---:|---|
| People | **3,318** | with `includeTrash=true`; **2,091 without** (1,227 Trash) |
| Events | **3,207** | rate-limited to 10/window — pace carefully |
| Deals  | **228**  | funnel join: all 228 link to a person |

Tiny compared to GHL (252k). A full backfill is seconds, not minutes —
sharding barely matters here, but we keep the discipline for portability.

### Trash filtering (IMPORTANT — caught a 1,227-row gap)

`GET /people` **silently excludes `stage="Trash"` people** by default (returns
2,091). Active Deals reference trashed people, so the funnel join had 45
orphans until we added `includeTrash=true`. The `People` resource now sets
`DEFAULT_PARAMS = {"includeTrash": "true"}` so we capture all 3,318. The
backend can filter on the `Stage` column. Check whether Deals/Events have an
analogous hidden filter before trusting their totals.

### Deals specifics

- Deals **400 on `?fields=allFields`** — custom fields come back **inline**.
- Account defines **1 deal custom field**: `customClosingDate` (date), via
  `GET /dealCustomFields` (separate from `/customFields`, which is People).
- Each deal has `people` (array of {id,name} — the funnel FK) and `users`
  (assigned agents). Mapper emits PrimaryPersonId/PersonIds/PersonNames +
  PrimaryUserId/UserIds/UserNames. 2 deals link multiple people.

### Timestamps

All People timestamps are clean **ISO 8601 UTC with `Z`** (`created`,
`updated`, `lastActivity`). No epoch-ms surprise like GHL's conversations.
`clean_utc_ts` still handles both, so new endpoints are covered.

### API key format



### Entity inventory (planned scope)

| Endpoint | Entity | Notes |
|---|---|---|
| `/identity` | who the API key belongs to | used by smoke test |
| `/people` | People (leads/contacts) | primary entity |
| `/deals` | Deals (transactions/opportunities) | per-account |
| `/events` | Events (activity log: emails, calls, web visits, etc.) | high volume |
| `/notes` | Notes attached to people/deals | |
| `/tasks` | Tasks assigned to users | |
| `/users` | Team members | ✅ dim (4); 200 |
| `/pipelines` | Pipeline definitions | ✅ dim (2); nested stages[] |
| `/stages` | **Person** stages only | ✅ dim; deal stages come from /pipelines (§2) |
| `/sources` | Lead sources | **404** — no such endpoint; Sources dim DERIVED |
| `/leadSources` | Lead sources (alt path) | **403** — non-owner scope |
| `/tags` | Tags | **403** — non-owner scope; Tags dim DERIVED |
| `/textMessages` | SMS | not yet |
| `/em` | Email events | not yet |

`/identity` + `/people?limit=1` are the two reads the smoke test depends on.

**API key scope:** the live key is non-owner — owner-level endpoints (`/tags`,
`/leadSources`) 403. Standing ask: an owner-scoped key + a registered
`X-System-Key` (also lifts the 10/window Events ceiling). Until then Sources/Tags
are derived from People.csv. See §2 "Sources/Tags are DERIVED".

---

## 6. Failures to expect (and the rules that prevent them)

The FUB extracts so far passed clean (0 audit issues across all three), but
these are the traps the GHL build taught us — keep them in mind for new
entities:

### 6.1 Embedded newlines in CSV → SQL Server `BULK INSERT` won't parse
Even RFC-compliant quoted fields with `\r\n` inside break BULK INSERT — 8 of
50 rows can silently disappear on re-read. **Fix (in place):** all text goes
through `clean_text` which replaces `\r`, `\n`, `\t` with a single space. The
audit gate compares physical lines vs logical CSV rows; they must match (it's
run automatically by `export.py`).

### 6.2 Audit's own parser must respect quoted multi-line fields
Use `csv.reader(path.open(newline=""))` — not `text.splitlines()` first. The
splitlines approach lies about embedded newlines.

### 6.3 Vendor returns epoch ms in some endpoints
GHL `/conversations/search` returned epoch ms; ISO elsewhere. `clean_utc_ts`
auto-detects (numeric ≥ 10^12 → ms; else sec; else ISO). Port it as-is —
it will likely save us on FUB too.

### 6.4 X-System headers can be silently ignored
If you forget them, FUB still responds but your integration shows up as
"Unidentified" in their dashboard. Not an error, but easy to miss.

---

## 7. Decisions made (and why)

| Decision | Reason |
|---|---|
| CSV-first, not direct SQL writes | Same as GHL — decouple extract from load |
| `csv.QUOTE_MINIMAL` + UTF-8 BOM + CRLF | Works with both BULK INSERT and Excel |
| PascalCase columns | Matches SQL Server convention, matches GHL output |
| `SourceSystem="FollowUpBoss"` | Distinguishes from `SourceSystem="GoHighLevel"` in same warehouse |
| Throttle floor ~6-7 RPS (well under 25 RPS plan ceiling) | Headroom; polite |
| Audit gate runs after every extract | User wants machine-enforced quality |
| Atomic checkpoint after every page | Resume must work mid-flight (user requirement) |
| `includeTrash=true` on People | Pull ALL raw data; active deals ref trashed people (§5) |
| Custom fields → own columns + `RawJson` | User: "pull all raw data, process on backend" |
| Number-typed custom fields kept as text | Preserve raw value; let SQL cast (TRY_CONVERT) |
| Throttle paces from per-endpoint `burst_limit` | Events is 10/window vs 125 — needs ~1 req/s |
| Staging table (all NVARCHAR) → typed via TRY_CONVERT | '' for INT/DATE/BIT breaks direct BULK INSERT |
| `schema.py` validated against mapper columns | DDL can never silently drift from the CSVs |

---

## 8. Status & backlog (START HERE in a new session)

### Done (all audited 0 issues, funnel joins 100%)

- ✅ Auth, client, throttle, sanitize, audit, batch framework — all built.
- ✅ **People** — 3,318 rows / 64 cols (incl. Trash, 22 custom fields, RawJson).
- ✅ **Deals** — 228 rows / 34 cols (1 custom field, people+users links).
- ✅ **Events** — 3,207 rows / 20 cols (paced under the 10/window limit).
- ✅ **SQL load path** — `create_tables.sql` + `staging_tables.sql` +
  `load_bulk_insert.sql`, all generated from `schema.py`. See §2 "SQL Server
  load path" for the run order.
- ✅ **Dimensions** — Users (4), Pipelines (2), Stages (20, unified), Sources
  (27, derived), Tags (32, derived). All audited 0 issues; every fact FK
  resolves 100%. See §2 "Dimension tables".
- ✅ **manifest.json** + 58 passing tests.

CSVs currently on disk in `data/exports/` (gitignored): People.csv, Deals.csv,
Events.csv, Users.csv, Pipelines.csv, Stages.csv, Sources.csv, Tags.csv,
manifest.json.

### Backlog (recommended order)

The user is loading this into **SQL Server very soon**. Priorities reflect that.

1. ✅ **Dimension tables** — DONE 2026-05-27. users/pipelines/stages/sources/tags.
   Stages is a union of two endpoints (§2 stages gap); sources/tags derived from
   People.csv (key is non-owner; §5). Next dim work would be re-pulling
   sources/tags live once an owner key + X-System-Key are registered.
2. ✅ **Referential-integrity check** — DONE 2026-05-27. `scripts/check_integrity.py`:
   11 declarative FK rules (People/Deals/Events → their dims), exit 1 on orphans.
   Currently 0 orphans across all 11. Multi-valued cols (Tags, PersonIds, UserIds)
   are pipe-split; empty FKs skipped (nullable). Unit-tested in test_integrity.py.
3. **`run_all.py` orchestrator** — extract every entity → manifest → one exit
   code, so a full refresh is a single command.
4. **Incremental/delta sync** — currently full backfill only. FUB supports
   `updatedAfter`-style filters; pull only changed rows on a schedule. This is
   where `batch.py`'s checkpoint earns its keep (store last-sync watermark).
5. **More activity entities** — `notes`, `tasks`, `calls`, `textMessages`,
   `em` (emails). Same mapper pattern; check rate limits per endpoint.
6. **Register an `X-System-Key`** — raises the rate-limit ceiling (esp. the
   10/window Events endpoint) and gets FUB API-change notifications. Currently
   unset; FUB nags in `_metadata.notice`.
7. **Scheduling / webhooks** — launchd/cron for recurring pulls, or webhook
   ingestion for near-real-time updates.

### How to add a new entity (the repeatable recipe)

1. Probe the endpoint shape with a throwaway script (full record keys, custom
   fields, rate-limit header, any hidden default filter like Trash).
2. `resources/<entity>.py` — subclass `Resource`, set `PATH`, `COLLECTION`,
   `DEFAULT_FIELDS`, `DEFAULT_PARAMS`. Register on `FUBClient.__init__`.
3. `mappers.py` — add `<ENTITY>_COLUMNS` + `map_<entity>` (PascalCase, FK
   columns, `RawJson`, audit columns). Every field through a `clean_*`.
4. `schema.py` — add the type map; `validate()` will enforce sync.
5. `scripts/export.py` REGISTRY + `scripts/audit_csv.py` PK_COLUMNS — add entries.
6. `scripts/export.py --entity <entity> --max-rows 100` (small POC) → audit
   green → full run → `generate_ddl.py` → `manifest.py`.

### Resolved (was an open question)

- Custom fields: **flattened to columns** (22 for People, 1 for Deals) AND the
  full record kept in `RawJson`. No junction table.
- Events scope: **full history** (only 3,207 rows — no date-windowing needed).
- Volumes: see §5 (tiny; sharding not needed but the framework is ready).

---

## 9. Resume (non-negotiable)

The user has explicitly flagged this: **resume must work mid-flight**.

- Checkpoint after **every page** — never batch checkpoint writes.
- **Atomic JSON write**: write to `<path>.tmp`, then `os.replace(tmp, path)`.
  A crash between the two leaves the old checkpoint intact; a crash before
  the tmp is fully flushed is also safe because `os.replace` is atomic.
- Checkpoint schema lives in `batch.py::Checkpoint`. Fields stored:
  `entity`, `extracted_at_utc`, `cursor`, `shard_index`,
  `rows_in_current_shard`, `rows_total`, `pages_fetched`, `finished`,
  `shard_files[]`, `updated_at_utc`.
- On restart, default `resume=True`: the extractor reads the checkpoint and
  continues writing into the current shard. It does **not** truncate
  partial shards — the audit gate catches actual corruption.
- "Resume test" is part of every entity's gate: extract N rows, kill the
  process, restart, confirm it picks up at row N+1 and the final manifest
  is identical to a single-run extract.

---

## 10. Memory references

Stored under `~/.claude/projects/-Users-smokestack-Projects-FUB-API/memory/`:

- `MEMORY.md` — index
- `project_fub_api.md` — FUB auth/pagination/rate-limit/trash quirks, volumes,
  account details, and the user's "pull all raw data" philosophy.

The cross-project memory from GHL_API also applies:

- `feedback-validate-before-scale` (in GHL's memory dir) — user requires
  small-scale POC + audit gate before scaling any extract. We've followed this
  throughout (100-row / small POC before every full pull).

---

## 11. Don't do these things

- **Don't** add new fields to CSVs without updating `mappers.py`, the SQL
  DDL, and the audit's expected columns.
- **Don't** call `csv.writer` directly with raw data — always sanitize first.
- **Don't** assume any API field is non-null. FUB People can have missing
  `emails`, `phones`, `assignedUserId`, `source`. Mappers must handle this.
- **Don't** commit `.env` or anything under `data/exports/`.
- **Don't** ship code that doesn't pass `pytest tests/ -v`.
- **Don't** skip the audit gate.
- **Don't** batch checkpoint writes. After every page. Atomic. Always.
- **Don't** raise concurrency without first observing actual `X-RateLimit-*`
  values — burst limits vary by FUB plan.
- **Don't** use `git rebase -i`, `--amend`, or force-push without explicit
  user permission. Create new commits.
