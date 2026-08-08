"""Mounted FastMCP application for the protected properties target."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.shared.claims import AuthenticationError, AuthorizationError, require_bearer
from app.targets.properties.service import PropertyStatus, QueryPropertiesInput

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.lifespan import AppRuntime


@dataclass(frozen=True)
class PropertiesRequestContext:
    """Validated target context bound to one ASGI request task."""

    runtime: AppRuntime
    service_token: str
    user_token: str
    request_id: str


properties_context: ContextVar[PropertiesRequestContext | None] = ContextVar(
    "properties_context", default=None
)

properties_mcp = FastMCP(
    "properties_mcp",
    instructions="Read property records visible to the independently authenticated tenant.",
    json_response=True,
    stateless_http=True,
    streamable_http_path="/",
)


@properties_mcp.tool(
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
    status: Annotated[
        PropertyStatus | None,
        Field(description="Optional property status"),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Maximum records to return", ge=1, le=20),
    ] = 10,
) -> dict[str, Any]:
    """Query property records visible to the authenticated tenant.

    Tenant scope is derived from a separately verified user-context JWT. This read-only
    tool never accepts tenant identity and queries only the protected SQLite view.
    """

    context = properties_context.get()
    if context is None:
        raise RuntimeError("Property target request context is unavailable")
    arguments = QueryPropertiesInput(
        property_id=property_id,
        city=city,
        status=status,
        limit=limit,
    )
    records = context.runtime.properties_target.query(
        service_token=context.service_token,
        user_token=context.user_token,
        arguments=arguments,
    )
    return {
        "records": records,
        "count": len(records),
        "total_count": len(records),
        "has_more": False,
        "request_id": context.request_id,
    }


def _forbid_extra_tool_arguments() -> None:
    """Make the generated target schema and validator reject unknown arguments."""

    tool = properties_mcp._tool_manager.get_tool(  # noqa: SLF001 - SDK has no public hook.
        "query_properties"
    )
    if tool is None:
        raise RuntimeError("Properties tool was not registered")
    tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
    tool.fn_metadata.arg_model.model_rebuild(force=True)
    tool.parameters = tool.fn_metadata.arg_model.model_json_schema(by_alias=True)


_forbid_extra_tool_arguments()


class PropertiesAuthMiddleware:
    """Require gateway service auth plus independently validated user context."""

    def __init__(self, app: ASGIApp, runtime_getter: Callable[[], AppRuntime]) -> None:
        self.app = app
        self.runtime_getter = runtime_getter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
        try:
            service_token = require_bearer(headers.get("authorization"))
            user_token = headers.get("x-user-token")
            if not user_token:
                raise AuthenticationError("Missing user context")
            runtime = self.runtime_getter()
            runtime.properties_target.validate_context(
                service_token=service_token,
                user_token=user_token,
            )
        except AuthenticationError as exc:
            await JSONResponse({"detail": str(exc)}, status_code=401)(scope, receive, send)
            return
        except AuthorizationError as exc:
            await JSONResponse({"detail": str(exc)}, status_code=403)(scope, receive, send)
            return
        context_token = properties_context.set(
            PropertiesRequestContext(
                runtime=runtime,
                service_token=service_token,
                user_token=user_token,
                request_id=headers.get("x-request-id", "unavailable"),
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            properties_context.reset(context_token)


def properties_asgi_app(runtime_getter: Callable[[], AppRuntime]) -> ASGIApp:
    """Return the protected Streamable HTTP target application."""

    return PropertiesAuthMiddleware(properties_mcp.streamable_http_app(), runtime_getter)
