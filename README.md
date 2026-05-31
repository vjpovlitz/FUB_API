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

See `CLAUDE.md` for the full handoff and `DATA_RULES.md` for the canonical
extraction rules.
