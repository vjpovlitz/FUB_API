# syntax=docker/dockerfile:1
#
# FUB warehouse app image — runs the Streamlit dashboard and/or the read-only
# MCP server (fub-mcp). Both reach the SQL Server warehouse via pyodbc, so the
# image ships the Microsoft ODBC Driver 18. Secrets are NOT baked in — they come
# from the environment at run time (docker compose `env_file: .env`).
#
# Build:  docker build -t fub-warehouse:latest .
# Run:    docker run --rm -p 8502:8502 --env-file .env fub-warehouse:latest

FROM python:3.12-slim-bookworm

# --- system deps: Microsoft ODBC Driver 18 (+ unixODBC) for pyodbc ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates apt-transport-https \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev \
    && apt-get purge -y --auto-remove curl gnupg apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# --- python deps first (layer-cached until pyproject/README change) ---------
# README.md is referenced by pyproject (readme = ...), so it must exist for the
# install. src/ is needed because the install targets the local packages.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install ".[dashboard,mcp]"

# --- app code ---------------------------------------------------------------
COPY dashboard/ ./dashboard/
COPY sql/ ./sql/
COPY scripts/ ./scripts/
COPY demo/ ./demo/
COPY .streamlit/ ./.streamlit/

# non-root runtime
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8502

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8502/_stcore/health', timeout=4).status==200 else 1)" || exit 1

# Default surface = the dashboard. Compose overrides `command` for the MCP service.
CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=8502", "--server.address=0.0.0.0", "--server.headless=true"]
