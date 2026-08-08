"""TVM service deriving order-store scope only from a signed capability."""

from __future__ import annotations

from app.auth.service import IdentityService
from app.auth.tokens import RSATokenAuthority
from app.settings import Settings
from app.shared.capability_tokens import (
    issue_store_credential,
    verify_tenant_capability,
)
from app.shared.claims import AuthorizationError


class TVMService:
    """Mint a short-lived store credential after two independent credential checks."""

    def __init__(
        self,
        *,
        identity: IdentityService,
        gateway_authority: RSATokenAuthority,
        settings: Settings,
    ) -> None:
        self.identity = identity
        self.gateway_authority = gateway_authority
        self.settings = settings

    def issue_order_store_credential(
        self,
        *,
        service_token: str,
        capability: str,
        request_id: str,
    ) -> str:
        """Issue read scope without accepting a tenant field from the caller."""

        self.identity.validate_service_token(
            service_token,
            audience="local-tvm",
            client_id=self.settings.orders_service_client_id,
            scope="credentials.issue",
        )
        claims = verify_tenant_capability(
            self.gateway_authority,
            capability,
            audience="local-tvm",
            expected_tool="query_orders",
        )
        if claims.get("request_id") != request_id:
            raise AuthorizationError("TVM request identifier does not match capability")
        return issue_store_credential(
            self.gateway_authority,
            tenant_id=claims["tenant_id"],
            request_id=request_id,
            ttl_seconds=self.settings.store_credential_ttl_seconds,
        )
