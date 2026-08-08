"""Public FastMCP gateway exposing exactly two tenant-implicit read tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.types import ASGIApp

from app.gateway.interceptor import GatewayAuthMiddleware, gateway_context
from app.targets.orders.service import OrderStatus, QueryOrdersInput
from app.targets.properties.service import PropertyStatus, QueryPropertiesInput

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.lifespan import AppRuntime

gateway_mcp = FastMCP(
    "multi_tenant_gateway_mcp",
    instructions=(
        "Read-only gateway. Tenant identity comes from verified authorization and must never "
        "be supplied as a tool argument."
    ),
    json_response=True,
    stateless_http=True,
    streamable_http_path="/",
)


@gateway_mcp.tool(
    name="query_orders",
    annotations=ToolAnnotations(
        title="Query tenant orders",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def query_orders(
    order_id: Annotated[
        str | None,
        Field(
            description="Optional order identifier, for example A-1001",
            pattern=r"^[A-Z]-\d{4}$",
            max_length=16,
        ),
    ] = None,
    status: Annotated[OrderStatus | None, Field(description="Optional order status")] = None,
    limit: Annotated[
        int,
        Field(description="Maximum records to return", ge=1, le=20),
    ] = 10,
) -> dict[str, Any]:
    """Query the authenticated tenant's order, payment, or refund records.

    Tenant identity is applied automatically. Never ask for or supply a tenant ID.
    Returns structured order records and a secret-free target trace.
    """

    context = gateway_context.get()
    if context is None:
        raise RuntimeError("Gateway request context is unavailable")
    return await context.runtime.gateway_router.query_orders(
        principal=context.principal,
        arguments=QueryOrdersInput(order_id=order_id, status=status, limit=limit),
        request_id=context.request_id,
    )


@gateway_mcp.tool(
    name="query_properties",
    annotations=ToolAnnotations(
        title="Query visible properties",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def query_properties(
    property_id: Annotated[
        str | None,
        Field(
            description="Optional property identifier, for example PA-101",
            pattern=r"^P[A-Z]-\d{3}$",
            max_length=16,
        ),
    ] = None,
    city: Annotated[
        str | None,
        Field(description="Optional exact city filter", min_length=1, max_length=80),
    ] = None,
    status: Annotated[PropertyStatus | None, Field(description="Optional property status")] = None,
    limit: Annotated[
        int,
        Field(description="Maximum records to return", ge=1, le=20),
    ] = 10,
) -> dict[str, Any]:
    """Query property records visible to the authenticated tenant.

    Tenant isolation is applied by independently validated user context and a protected
    datastore view. Never ask for or supply a tenant ID.
    """

    context = gateway_context.get()
    if context is None:
        raise RuntimeError("Gateway request context is unavailable")
    return await context.runtime.gateway_router.query_properties(
        principal=context.principal,
        arguments=QueryPropertiesInput(
            property_id=property_id,
            city=city,
            status=status,
            limit=limit,
        ),
        request_id=context.request_id,
    )


def _forbid_extra_tool_arguments() -> None:
    """Make generated FastMCP signature models fail closed on unknown arguments."""

    for name in ("query_orders", "query_properties"):
        tool = gateway_mcp._tool_manager.get_tool(name)  # noqa: SLF001 - SDK has no public schema hook.
        if tool is None:
            raise RuntimeError(f"Gateway tool was not registered: {name}")
        tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
        tool.fn_metadata.arg_model.model_rebuild(force=True)
        tool.parameters = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)


_forbid_extra_tool_arguments()


def gateway_asgi_app(runtime_getter: Callable[[], AppRuntime]) -> ASGIApp:
    """Return the authenticated public Streamable HTTP application."""

    return GatewayAuthMiddleware(gateway_mcp.streamable_http_app(), runtime_getter)
