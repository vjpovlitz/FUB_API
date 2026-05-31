# FUB_API

Python client and ETL for the **Follow Up Boss** API. Extracts People / Deals /
Events (and friends) into SQL-Server-shaped CSVs for warehouse load.

Sister project to [GHL_API](../DCR/GHL_API). Same CSV-first discipline, same
audit gates, same atomic-checkpoint resume pattern — tuned to FUB's auth model
(HTTP Basic + `X-System*` headers) and pagination style (offset/limit).

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# fill in FUB_API_KEY

python scripts/smoke_test.py
```

## Run with Docker

The app image bundles the Microsoft ODBC Driver 18, so `pyodbc` works out of the
box. Secrets are never baked in — they come from `.env` at run time.

```bash
cp .env.example .env          # fill in FUB_API_KEY + the SQL warehouse vars

# Dashboard -> http://localhost:8502
docker compose up dashboard

# Read-only MCP server (stdio; opt-in profile)
docker compose run --rm mcp

# Or build/run the image directly
docker build -t fub-warehouse:latest .
docker run --rm -p 8502:8502 --env-file .env fub-warehouse:latest
```

The container connects to your **existing** SQL Server warehouse via the
`GHL_SQL_*` / `MCP_SQL_*` env vars; it does not create or own a database. If the
warehouse is on a Tailscale/VPN address, make sure the Docker host can reach it
(on Linux, uncomment `network_mode: host` in `docker-compose.yml`).

### Self-contained demo (no external DB, no real data)

For a zero-setup walkthrough — bundled SQL Server + synthetic, non-PII data —
use the demo compose file:

```bash
docker compose -f docker-compose.demo.yml up --build
# -> http://localhost:8502  (synthetic data spanning both CRMs)
```

It boots a local SQL Server, seeds `dcr_demo` with fake contacts / deals /
activity (see `demo/seed_demo.py` — names from fixed lists, `@example.com`
emails, random dates; **no Follow Up Boss or GoHighLevel data is touched**),
then starts the dashboard against it. Tear down with:

```bash
docker compose -f docker-compose.demo.yml down -v   # -v also drops the demo DB volume
```

> Apple Silicon: SQL Server runs under amd64 emulation (pinned in the compose
> file); first boot takes a couple of minutes and needs ~2.5 GB RAM allotted to
> Docker. The demo SA password is a throwaway local credential, not a secret.

See `CLAUDE.md` for the full handoff and `DATA_RULES.md` for the canonical
extraction rules.
