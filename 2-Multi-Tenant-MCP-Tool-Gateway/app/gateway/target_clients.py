"""Replaceable internal clients preserving mounted target transport boundaries."""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from app.settings import Settings
from app.targets.orders.service import OrdersTargetService
from app.targets.properties.service import PropertiesTargetService, QueryPropertiesInput


class OrdersClient(Protocol):
    """Boundary for mounted or future external Lambda-style order targets."""

    async def invoke(
        self,
        *,
        service_token: str,
        envelope: dict[str, Any],
    ) -> list[dict[str, Any]]: ...


class OrdersHTTPClient:
    """Call the mounted orders target with its explicit service/envelope contract."""

    def __init__(
        self,
        *,
        settings: Settings,
        in_process_service: OrdersTargetService,
    ) -> None:
        self.settings = settings
        self.in_process_service = in_process_service

    async def invoke(
        self,
        *,
        service_token: str,
        envelope: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Use loopback HTTP in the runnable app and the same service contract in tests."""

        if self.settings.testing:
            return await self.in_process_service.invoke(
                authorization=service_token,
                envelope=envelope,
            )
        async with httpx.AsyncClient(
            timeout=self.settings.internal_timeout_seconds,
        ) as client:
            response = await client.post(
                self.settings.orders_target_url,
                headers={"Authorization": f"Bearer {service_token}"},
                json=envelope,
            )
        response.raise_for_status()
        records = response.json().get("records", [])
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError("Orders target returned an invalid record payload")
        return records


class PropertiesClient(Protocol):
    """Boundary for mounted or future external properties MCP transports."""

    async def query(
        self,
        *,
        service_token: str,
        user_token: str,
        request_id: str,
        arguments: QueryPropertiesInput,
    ) -> list[dict[str, Any]]: ...


class PropertiesMCPClient:
    """Call the protected properties target over official MCP Streamable HTTP."""

    def __init__(
        self,
        *,
        settings: Settings,
        in_process_service: PropertiesTargetService,
    ) -> None:
        self.settings = settings
        self.in_process_service = in_process_service

    async def query(
        self,
        *,
        service_token: str,
        user_token: str,
        request_id: str,
        arguments: QueryPropertiesInput,
    ) -> list[dict[str, Any]]:
        """Use loopback MCP in the runnable app and an equivalent direct adapter in tests."""

        if self.settings.testing:
            return self.in_process_service.query(
                service_token=service_token,
                user_token=user_token,
                arguments=arguments,
            )
        headers = {
            "Authorization": f"Bearer {service_token}",
            "X-User-Token": user_token,
            "X-Request-ID": request_id,
        }
        timeout = httpx.Timeout(self.settings.internal_timeout_seconds)
        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        ) as http_client:
            async with streamable_http_client(
                self.settings.properties_mcp_url,
                http_client=http_client,
            ) as (read_stream, write_stream, _session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "query_properties",
                        arguments=arguments.model_dump(mode="json", exclude_none=True),
                    )
        if result.isError:
            raise RuntimeError("Properties MCP target returned a tool error")
        payload = result.structuredContent
        if payload is None:
            text = next(
                (item.text for item in result.content if isinstance(item, TextContent)),
                "{}",
            )
            decoded = json.loads(text)
            payload = decoded if isinstance(decoded, dict) else {}
        records = payload.get("records", [])
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise RuntimeError("Properties MCP target returned an invalid record payload")
        return records
