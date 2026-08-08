"""Independent service/user verification and tenant-view property querying."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.auth.service import IdentityService
from app.auth.tokens import JWKSCache, verify_user_with_jwks
from app.settings import Settings
from app.shared.claims import AuthenticationError, AuthorizationError, normalize_tenant_claim
from app.stores.property_store import PropertyStore
from app.stores.sqlite import SQLiteStore


class PropertyStatus(StrEnum):
    """Supported property states."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class QueryPropertiesInput(BaseModel):
    """Model-controlled property filters; tenant identity is intentionally absent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    property_id: str | None = Field(default=None, pattern=r"^P[A-Z]-\d{3}$", max_length=16)
    city: str | None = Field(default=None, min_length=1, max_length=80)
    status: PropertyStatus | None = None
    limit: int = Field(default=10, ge=1, le=20)


class PropertiesTargetService:
    """Validate gateway authorization and user context as separate credentials."""

    def __init__(
        self,
        *,
        identity: IdentityService,
        user_jwks: JWKSCache,
        store: SQLiteStore,
        property_store: PropertyStore,
        settings: Settings,
    ) -> None:
        self.identity = identity
        self.user_jwks = user_jwks
        self.store = store
        self.property_store = property_store
        self.settings = settings

    def validate_context(self, *, service_token: str, user_token: str) -> dict[str, Any]:
        """Verify both tokens for their distinct audience and purpose."""

        self.identity.validate_service_token(
            service_token,
            audience="properties-mcp",
            client_id=self.settings.gateway_service_client_id,
            scope="mcp.tools.call",
        )
        claims = verify_user_with_jwks(
            user_token,
            cache=self.user_jwks,
            issuer=self.settings.identity_issuer,
            audience="properties-mcp-user-context",
        )
        tenant_id = normalize_tenant_claim(claims)
        if self.store.tenant(tenant_id) is None:
            raise AuthorizationError("Unknown or inactive tenant")
        return claims

    def query(
        self,
        *,
        service_token: str,
        user_token: str,
        arguments: QueryPropertiesInput,
    ) -> list[dict[str, Any]]:
        """Create one connection-local scope and query only its protected view."""

        claims = self.validate_context(service_token=service_token, user_token=user_token)
        tenant_id = normalize_tenant_claim(claims)
        return self.property_store.query(
            tenant_id=tenant_id,
            property_id=arguments.property_id,
            city=arguments.city,
            status=arguments.status.value if arguments.status else None,
            limit=arguments.limit,
        )


def safe_properties_error(exc: Exception) -> str:
    """Map target failures to a non-revealing tool message."""

    if isinstance(exc, (AuthenticationError, AuthorizationError)):
        return "Property access was denied by the target."
    return "The property target could not complete the read."
