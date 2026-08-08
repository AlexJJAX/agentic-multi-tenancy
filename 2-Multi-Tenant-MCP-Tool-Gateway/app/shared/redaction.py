"""Structured secret redaction for logs and audit details."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SENSITIVE_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "jwt",
    "openai_api_key",
    "private_key",
    "secret",
    "token",
    "x-tenant-context",
    "x-user-token",
)


def is_sensitive_key(key: str) -> bool:
    """Return whether a key name represents secret-bearing material."""

    normalized = key.lower().replace("_", "-")
    return any(part.replace("_", "-") in normalized for part in SENSITIVE_PARTS)


def redact(value: Any) -> Any:
    """Recursively replace values associated with secret-like keys."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if is_sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    return value
