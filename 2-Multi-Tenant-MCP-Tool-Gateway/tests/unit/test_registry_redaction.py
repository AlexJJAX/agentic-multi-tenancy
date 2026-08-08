"""Static registry and structured redaction tests."""

from __future__ import annotations

import pytest

from app.gateway.registry import TargetRegistry
from app.shared.redaction import redact


def test_registry_contains_only_approved_read_tools() -> None:
    registry = TargetRegistry.load()
    assert set(registry.targets) == {"query_orders", "query_properties"}
    assert registry.get("query_orders").path.startswith("/internal/")
    with pytest.raises(ValueError, match="Unknown"):
        registry.get("delete_orders")


def test_redaction_recurses_without_removing_safe_diagnostics() -> None:
    payload = {
        "authorization": "Bearer secret",
        "nested": {
            "x-user-token": "jwt",
            "client_secret": "secret",
            "request_id": "safe-id",
        },
        "items": [{"credential": "scope", "status": "denied"}],
    }
    safe = redact(payload)
    assert safe["authorization"] == "[REDACTED]"
    assert safe["nested"]["x-user-token"] == "[REDACTED]"
    assert safe["nested"]["client_secret"] == "[REDACTED]"
    assert safe["nested"]["request_id"] == "safe-id"
    assert safe["items"][0]["credential"] == "[REDACTED]"
    assert safe["items"][0]["status"] == "denied"
