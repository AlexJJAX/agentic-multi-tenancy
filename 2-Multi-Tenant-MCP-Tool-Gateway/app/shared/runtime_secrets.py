"""Generated development secrets kept exclusively beneath ``.local``."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass

from app.settings import Settings


@dataclass(frozen=True)
class RuntimeSecrets:
    """Secrets used by local browser and service clients."""

    session_secret: str
    gateway_service_client_secret: str
    orders_service_client_secret: str


def load_or_create_runtime_secrets(settings: Settings) -> RuntimeSecrets:
    """Load stable demo secrets, generating missing values without logging them."""

    path = settings.runtime_dir / "secrets.json"
    stored: dict[str, str] = {}
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))

    values = {
        "session_secret": settings.session_secret
        or stored.get("session_secret")
        or secrets.token_urlsafe(48),
        "gateway_service_client_secret": settings.gateway_service_client_secret
        or stored.get("gateway_service_client_secret")
        or secrets.token_urlsafe(48),
        "orders_service_client_secret": settings.orders_service_client_secret
        or stored.get("orders_service_client_secret")
        or secrets.token_urlsafe(48),
    }
    if values != stored:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values), encoding="utf-8")
        os.chmod(path, 0o600)
    return RuntimeSecrets(**values)
