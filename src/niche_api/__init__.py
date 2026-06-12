"""Niche Data (customers-api.nichedata.ai) client + ETL source.

Pulls distressed-property "notices" (foreclosures, lis-pendens/NOD, pre-probate,
probates, liens, estate-sales, guardianships, divorces) and feeds the DCR
warehouse + Follow Up Boss, mirroring the fub_api source patterns.
"""
from _tls_bootstrap import ensure_os_trust_store as _ensure_os_trust_store

_ensure_os_trust_store()  # honor OS trust store (Norton TLS scanning on Windows)

from niche_api.client import NicheClient

__all__ = ["NicheClient"]
