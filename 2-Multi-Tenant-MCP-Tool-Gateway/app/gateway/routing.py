"""Gateway routing that preserves target-specific authentication contracts."""

from __future__ import annotations

import time
from typing import Any

from app.audit.repository import AuditRepository
from app.auth.tokens import RSATokenAuthority
from app.gateway.registry import TargetRegistry
from app.gateway.service_tokens import ServiceTokenCache
from app.gateway.target_clients import OrdersClient, PropertiesClient
from app.settings import Settings
from app.shared.capability_tokens import issue_tenant_capability
from app.shared.models import Principal
from app.shared.runtime_secrets import RuntimeSecrets
from app.targets.orders.service import QueryOrdersInput
from app.targets.properties.service import QueryPropertiesInput


class GatewayRouter:
    """Route approved read tools without reading business data at the gateway."""

    def __init__(
        self,
        *,
        registry: TargetRegistry,
        token_cache: ServiceTokenCache,
        gateway_authority: RSATokenAuthority,
        orders_client: OrdersClient,
        properties_client: PropertiesClient,
        audit: AuditRepository,
        settings: Settings,
        secrets: RuntimeSecrets,
    ) -> None:
        self.registry = registry
        self.token_cache = token_cache
        self.gateway_authority = gateway_authority
        self.orders_client = orders_client
        self.properties_client = properties_client
        self.audit = audit
        self.settings = settings
        self.secrets = secrets

    async def query_orders(
        self,
        *,
        principal: Principal,
        arguments: QueryOrdersInput,
        request_id: str,
    ) -> dict[str, Any]:
        """Inject trusted tenant capability and invoke the Lambda-style target."""

        target = self.registry.get("query_orders")
        started = time.perf_counter()
        try:
            service_token = self.token_cache.get(
                client_id=self.settings.gateway_service_client_id,
                client_secret=self.secrets.gateway_service_client_secret,
                audience="orders-target",
                scope="tools.invoke",
            )
            capability = issue_tenant_capability(
                self.gateway_authority,
                tenant_id=principal.tenant_id,
                tool="query_orders",
                request_id=request_id,
                ttl_seconds=self.settings.capability_ttl_seconds,
            )
            envelope = {
                "tool_name": "query_orders",
                "arguments": arguments.model_dump(mode="json", exclude_none=True),
                "request_context": {
                    "request_id": request_id,
                    "client_context": {
                        "custom": {
                            "bedrockAgentCorePropagatedHeaders": {
                                "x-tenant-id": principal.tenant_id,
                                "x-tenant-context": capability,
                                "x-request-id": request_id,
                            }
                        }
                    },
                },
            }
            records = await self.orders_client.invoke(
                service_token=service_token,
                envelope=envelope,
            )
        except Exception:
            self._audit(
                principal=principal,
                request_id=request_id,
                tool="query_orders",
                target=target.path,
                decision="error",
                started=started,
                status_code=502,
            )
            raise
        self._audit(
            principal=principal,
            request_id=request_id,
            tool="query_orders",
            target=target.path,
            decision="allowed",
            started=started,
            status_code=200,
        )
        return self._result("query_orders", target.path, request_id, started, records)

    async def query_properties(
        self,
        *,
        principal: Principal,
        arguments: QueryPropertiesInput,
        request_id: str,
    ) -> dict[str, Any]:
        """Use service authorization while propagating the user JWT only as context."""

        target = self.registry.get("query_properties")
        started = time.perf_counter()
        try:
            service_token = self.token_cache.get(
                client_id=self.settings.gateway_service_client_id,
                client_secret=self.secrets.gateway_service_client_secret,
                audience="properties-mcp",
                scope="mcp.tools.call",
            )
            records = await self.properties_client.query(
                service_token=service_token,
                user_token=principal.token,
                request_id=request_id,
                arguments=arguments,
            )
        except Exception:
            self._audit(
                principal=principal,
                request_id=request_id,
                tool="query_properties",
                target=target.path,
                decision="error",
                started=started,
                status_code=502,
            )
            raise
        self._audit(
            principal=principal,
            request_id=request_id,
            tool="query_properties",
            target=target.path,
            decision="allowed",
            started=started,
            status_code=200,
        )
        return self._result("query_properties", target.path, request_id, started, records)

    def _audit(
        self,
        *,
        principal: Principal,
        request_id: str,
        tool: str,
        target: str,
        decision: str,
        started: float,
        status_code: int,
    ) -> None:
        self.audit.record(
            request_id=request_id,
            service="mcp-gateway",
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            action=tool,
            target=target,
            decision=decision,
            status_code=status_code,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _result(
        tool: str,
        target: str,
        request_id: str,
        started: float,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "tool": tool,
            "records": records,
            "count": len(records),
            "total_count": len(records),
            "has_more": False,
            "trace": {
                "tool": tool,
                "target": target,
                "request_id": request_id,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "outcome": "allowed",
            },
        }
