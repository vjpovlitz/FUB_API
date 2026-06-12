"""Smoke test: verify the API key in .env can talk to FUB.

Hits a few low-risk read endpoints, prints the response shape and the
rate-limit headers, and surfaces what the API tells us about ourselves.
Read-only — safe to re-run.
"""
from __future__ import annotations

import base64
import json
import os
import sys

import httpx
from dotenv import load_dotenv

# Honor the OS trust store (Norton TLS scanning on Windows presents a leaf cert
# signed by a root that's in the Windows store but not in certifi's bundle).
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 — best-effort; no-op where truststore is absent
    pass

load_dotenv()

API_KEY = os.getenv("FUB_API_KEY", "").strip()
X_SYSTEM = os.getenv("FUB_X_SYSTEM", "").strip()
X_SYSTEM_KEY = os.getenv("FUB_X_SYSTEM_KEY", "").strip()
BASE = os.getenv("FUB_BASE_URL", "https://api.followupboss.com/v1").rstrip("/")

if not API_KEY:
    print("ERROR: FUB_API_KEY is empty in .env")
    sys.exit(1)

# FUB Basic auth: api_key as username, empty password
auth_token = base64.b64encode(f"{API_KEY}:".encode("utf-8")).decode("ascii")

HEADERS = {
    "Authorization": f"Basic {auth_token}",
    "Accept": "application/json",
}
if X_SYSTEM:
    HEADERS["X-System"] = X_SYSTEM
if X_SYSTEM_KEY:
    HEADERS["X-System-Key"] = X_SYSTEM_KEY

RATELIMIT_HDRS = (
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
    "Retry-After",
)


def show(label: str, resp: httpx.Response) -> None:
    print(f"\n--- {label}  [{resp.status_code} {resp.reason_phrase}] ---")
    rl = {h: resp.headers.get(h) for h in RATELIMIT_HDRS if resp.headers.get(h) is not None}
    if rl:
        print(f"  rate-limit headers: {rl}")
    body = resp.text
    if not body:
        print("  (empty body)")
        return
    # Pretty-print JSON if we can, else raw text
    try:
        parsed = json.loads(body)
        pretty = json.dumps(parsed, indent=2, default=str)
        snippet = pretty[:1200] + ("..." if len(pretty) > 1200 else "")
    except Exception:
        snippet = body[:1200] + ("..." if len(body) > 1200 else "")
    print(snippet)


def main() -> None:
    print(f"API key length:  {len(API_KEY)} chars")
    print(f"API key prefix:  {API_KEY[:6]}...  (redacted)")
    print(f"X-System:        {X_SYSTEM or '(not set)'}")
    print(f"X-System-Key:    {'<set>' if X_SYSTEM_KEY else '(not set)'}")
    print(f"Base URL:        {BASE}")

    with httpx.Client(timeout=15.0, headers=HEADERS) as c:
        # /identity returns the account + user attached to this API key.
        # If this works, auth is correct.
        show("GET /identity", c.get(f"{BASE}/identity"))

        # 1 person — tiniest possible read, confirms list pagination shape.
        show("GET /people?limit=1", c.get(f"{BASE}/people", params={"limit": 1}))

        # 1 event — confirms the activity-log endpoint.
        show("GET /events?limit=1", c.get(f"{BASE}/events", params={"limit": 1}))

        # 1 deal — may 404 / be empty if the account doesn't use Deals; that's fine.
        show("GET /deals?limit=1", c.get(f"{BASE}/deals", params={"limit": 1}))


if __name__ == "__main__":
    main()
