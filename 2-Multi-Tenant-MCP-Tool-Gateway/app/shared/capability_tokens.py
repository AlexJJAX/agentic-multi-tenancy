"""Purpose-specific gateway capabilities and TVM store credentials."""

from __future__ import annotations

from typing import Any

from app.auth.tokens import RSATokenAuthority
from app.shared.claims import AuthorizationError, normalize_tenant_claim


def issue_tenant_capability(
    authority: RSATokenAuthority,
    *,
    tenant_id: str,
    tool: str,
    request_id: str,
    ttl_seconds: int,
) -> str:
    """Issue one gateway capability usable only by the orders target and TVM."""

    return authority.issue(
        subject="mcp-gateway",
        audience=["orders-target", "local-tvm"],
        ttl_seconds=min(ttl_seconds, 60),
        claims={"tenant_id": tenant_id, "tool": tool, "request_id": request_id},
    )


def verify_tenant_capability(
    authority: RSATokenAuthority,
    token: str,
    *,
    audience: str,
    expected_tool: str,
) -> dict[str, Any]:
    """Verify a capability and enforce its single-tool restriction."""

    claims = authority.decode(token, audience=audience)
    if claims.get("tool") != expected_tool:
        raise AuthorizationError("Capability is not valid for this tool")
    normalize_tenant_claim(claims)
    return claims


def issue_store_credential(
    authority: RSATokenAuthority,
    *,
    tenant_id: str,
    request_id: str,
    ttl_seconds: int,
) -> str:
    """Issue a read-only capability for one tenant-prefixed order namespace."""

    return authority.issue(
        subject="local-tvm",
        audience="order-store",
        ttl_seconds=min(ttl_seconds, 60),
        claims={
            "tenant_id": tenant_id,
            "request_id": request_id,
            "prefix": f"tenant:{tenant_id}:orders:",
            "operations": ["get", "mget", "hgetall"],
        },
    )


def verify_store_credential(authority: RSATokenAuthority, token: str) -> dict[str, Any]:
    """Validate a TVM credential and its non-empty read-only scope."""

    claims = authority.decode(token, audience="order-store")
    tenant_id = normalize_tenant_claim(claims)
    expected_prefix = f"tenant:{tenant_id}:orders:"
    if claims.get("prefix") != expected_prefix:
        raise AuthorizationError("Order-store prefix is invalid")
    operations = claims.get("operations")
    if (
        not isinstance(operations, list)
        or not operations
        or not set(operations)
        <= {
            "get",
            "mget",
            "hgetall",
        }
    ):
        raise AuthorizationError("Order-store operations are invalid")
    return claims
