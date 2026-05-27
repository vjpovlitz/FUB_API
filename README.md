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

See `CLAUDE.md` for the full handoff and `DATA_RULES.md` for the canonical
extraction rules.
