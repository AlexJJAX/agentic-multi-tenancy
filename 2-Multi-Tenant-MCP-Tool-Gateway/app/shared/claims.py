"""Claim normalization and validation helpers."""

from __future__ import annotations

import re
from typing import Any

TENANT_ID_PATTERN = re.compile(r"^tenant-[A-Za-z0-9][A-Za-z0-9_-]{0,55}$")


class AuthenticationError(ValueError):
    """Raised when a credential cannot be authenticated."""


class AuthorizationError(ValueError):
    """Raised when an authenticated identity lacks permission."""


def normalize_tenant_claim(claims: dict[str, Any]) -> str:
    """Normalize the supported tenant claim and reject ambiguity or malformed values."""

    primary = claims.get("tenant_id")
    compatibility = claims.get("custom:tenant_id")
    if primary and compatibility and primary != compatibility:
        raise AuthorizationError("Conflicting tenant claims")
    tenant_id = primary or compatibility
    if not isinstance(tenant_id, str) or not TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise AuthorizationError("Missing or malformed tenant claim")
    return tenant_id


def require_bearer(value: str | None) -> str:
    """Extract an RFC 6750 bearer value without accepting query-string credentials."""

    if not value:
        raise AuthenticationError("Missing bearer token")
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("Invalid bearer authorization header")
    return token.strip()
