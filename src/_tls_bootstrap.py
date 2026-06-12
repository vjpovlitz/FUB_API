"""Best-effort: make Python trust the OS certificate store.

On the Windows dev box, Norton Antivirus performs HTTPS/TLS scanning — it
MITMs outbound TLS and presents a leaf cert signed by its own root
("Norton Web/Mail Shield Root"). That root is installed in the Windows trust
store but NOT in certifi's bundle, so httpx/requests fail every HTTPS call with
"CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate".

`truststore` redirects Python's ssl module to the OS trust store (Windows
SChannel / macOS Security framework), which already trusts that root — so
verification stays ON (no insecure shortcut) and just consults the right store.

This is a no-op import everywhere truststore isn't installed (e.g. the macOS
box, where certifi already works), so it is safe to call unconditionally.
"""
from __future__ import annotations


def ensure_os_trust_store() -> bool:
    """Inject the OS trust store into ssl. Returns True if applied."""
    try:
        import truststore
    except ImportError:
        return False
    try:
        truststore.inject_into_ssl()
        return True
    except Exception:  # noqa: BLE001 — never let TLS bootstrap crash a caller
        return False
