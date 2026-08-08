"""Public gateway authentication and spoofed-context stripping middleware."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth.tokens import verify_user_with_jwks
from app.shared.claims import (
    AuthenticationError,
    AuthorizationError,
    normalize_tenant_claim,
    require_bearer,
)
from app.shared.correlation import correlation_id
from app.shared.models import Principal

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.lifespan import AppRuntime

UNTRUSTED_CONTEXT_HEADERS = {b"x-tenant-id", b"x-tenant-context", b"x-user-token"}


@dataclass(frozen=True)
class GatewayRequestContext:
    """Trusted request-local principal and correlation state."""

    runtime: AppRuntime
    principal: Principal
    request_id: str


gateway_context: ContextVar[GatewayRequestContext | None] = ContextVar(
    "gateway_context", default=None
)


class GatewayAuthMiddleware:
    """Authenticate every MCP request and discard all client tenant-context headers."""

    def __init__(self, app: ASGIApp, runtime_getter: Callable[[], AppRuntime]) -> None:
        self.app = app
        self.runtime_getter = runtime_getter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        original_headers = scope.get("headers", [])
        headers = {key.decode().lower(): value.decode() for key, value in original_headers}
        request_id = correlation_id(headers.get("x-request-id"))
        runtime = self.runtime_getter()
        try:
            token = require_bearer(headers.get("authorization"))
            claims = verify_user_with_jwks(
                token,
                cache=runtime.gateway_user_jwks,
                issuer=runtime.settings.identity_issuer,
                audience="mcp-gateway",
            )
            tenant_id = normalize_tenant_claim(claims)
            if runtime.store.tenant(tenant_id) is None:
                raise AuthorizationError("Unknown or inactive tenant")
            principal = Principal(
                user_id=claims["sub"],
                username=claims["preferred_username"],
                tenant_id=tenant_id,
                token=token,
            )
        except AuthenticationError as exc:
            await JSONResponse({"detail": str(exc)}, status_code=401)(scope, receive, send)
            return
        except AuthorizationError as exc:
            await JSONResponse({"detail": str(exc)}, status_code=403)(scope, receive, send)
            return
        spoofed = sorted(
            key.decode()
            for key, _value in original_headers
            if key.lower() in UNTRUSTED_CONTEXT_HEADERS
        )
        if spoofed:
            runtime.audit.record(
                request_id=request_id,
                service="mcp-gateway",
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                action="strip_untrusted_context",
                target="gateway-interceptor",
                decision="stripped",
                status_code=200,
                details={"header_names": spoofed},
            )
        clean_scope = dict(scope)
        clean_scope["headers"] = [
            (key, value)
            for key, value in original_headers
            if key.lower() not in UNTRUSTED_CONTEXT_HEADERS
        ]
        context_token = gateway_context.set(
            GatewayRequestContext(runtime=runtime, principal=principal, request_id=request_id)
        )
        try:
            await self.app(clean_scope, receive, send)
        finally:
            gateway_context.reset(context_token)
