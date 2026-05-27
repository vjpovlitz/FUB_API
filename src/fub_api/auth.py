"""FUB credentials.

FUB uses HTTP Basic auth: API key as the username, empty password.
Every request should also carry X-System (integration name) and X-System-Key
(UUID) headers so FUB can identify the integration. The system key is optional
for unregistered integrations.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass


@dataclass
class BasicAuthCredentials:
    api_key: str
    system: str | None = None        # X-System header value
    system_key: str | None = None    # X-System-Key header value (UUID)

    def auth_header(self) -> dict[str, str]:
        # Basic auth: "<api_key>:" base64-encoded. Password is empty.
        token = base64.b64encode(f"{self.api_key}:".encode("utf-8")).decode("ascii")
        headers = {"Authorization": f"Basic {token}"}
        if self.system:
            headers["X-System"] = self.system
        if self.system_key:
            headers["X-System-Key"] = self.system_key
        return headers
