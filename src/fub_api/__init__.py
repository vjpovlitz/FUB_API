"""Python client and ETL for the Follow Up Boss API."""
from _tls_bootstrap import ensure_os_trust_store as _ensure_os_trust_store

_ensure_os_trust_store()  # honor OS trust store (Norton TLS scanning on Windows)

from fub_api.client import FUBClient

__all__ = ["FUBClient"]
