"""Orders target contract validation and scoped store invocation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.auth.service import IdentityService
from app.auth.tokens import RSATokenAuthority
from app.gateway.service_tokens import ServiceTokenCache
from app.settings import Settings
from app.shared.capability_tokens import verify_tenant_capability
from app.shared.claims import AuthorizationError
from app.shared.runtime_secrets import RuntimeSecrets
from app.stores.order_store import OrderStore
from app.tvm.service import TVMService


class OrderStatus(StrEnum):
    """Supported read-only order states."""

    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    RETURNED = "returned"


class QueryOrdersInput(BaseModel):
    """Model-controlled order filters; tenant identity is intentionally absent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order_id: str | None = Field(default=None, pattern=r"^[A-Z]-\d{4}$", max_length=16)
    status: OrderStatus | None = None
    limit: int = Field(default=10, ge=1, le=20)


class OrdersTargetService:
    """Validate the Lambda-like envelope before requesting a TVM credential."""

    def __init__(
        self,
        *,
        identity: IdentityService,
        gateway_authority: RSATokenAuthority,
        token_cache: ServiceTokenCache,
        tvm: TVMService,
        order_store: OrderStore,
        settings: Settings,
        secrets: RuntimeSecrets,
    ) -> None:
        self.identity = identity
        self.gateway_authority = gateway_authority
        self.token_cache = token_cache
        self.tvm = tvm
        self.order_store = order_store
        self.settings = settings
        self.secrets = secrets

    async def invoke(self, *, authorization: str, envelope: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute ``query_orders`` only when all propagated identity context agrees."""

        self.identity.validate_service_token(
            authorization,
            audience="orders-target",
            client_id=self.settings.gateway_service_client_id,
            scope="tools.invoke",
        )
        if envelope.get("tool_name") != "query_orders":
            raise AuthorizationError("Orders target accepts only query_orders")
        arguments = QueryOrdersInput.model_validate(envelope.get("arguments", {}))
        request_context = envelope.get("request_context", {})
        request_id = request_context.get("request_id")
        headers = (
            request_context.get("client_context", {})
            .get("custom", {})
            .get("bedrockAgentCorePropagatedHeaders", {})
        )
        capability = headers.get("x-tenant-context")
        tenant_header = headers.get("x-tenant-id")
        if not isinstance(request_id, str) or not isinstance(capability, str):
            raise AuthorizationError("Orders invocation context is incomplete")
        claims = verify_tenant_capability(
            self.gateway_authority,
            capability,
            audience="orders-target",
            expected_tool="query_orders",
        )
        if (
            tenant_header != claims["tenant_id"]
            or headers.get("x-request-id") != request_id
            or claims.get("request_id") != request_id
        ):
            raise AuthorizationError("Orders tenant or request context does not agree")
        tvm_service_token = self.token_cache.get(
            client_id=self.settings.orders_service_client_id,
            client_secret=self.secrets.orders_service_client_secret,
            audience="local-tvm",
            scope="credentials.issue",
        )
        credential = self.tvm.issue_order_store_credential(
            service_token=tvm_service_token,
            capability=capability,
            request_id=request_id,
        )
        return await self.order_store.query(
            credential=credential,
            order_id=arguments.order_id,
            status=arguments.status.value if arguments.status else None,
            limit=arguments.limit,
        )
