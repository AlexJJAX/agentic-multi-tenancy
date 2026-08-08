"""Per-request LangChain MCP tool loading with non-reused user authorization."""

from __future__ import annotations

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StreamableHttpConnection

from app.settings import Settings


class GatewayToolLoader:
    """Create fresh MCP connection configuration for each authenticated chat request."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def load(self, *, user_token: str, request_id: str) -> list[BaseTool]:
        """Load gateway tools with headers that cannot be shared across users."""

        connection: StreamableHttpConnection = {
            "transport": "streamable_http",
            "url": self.settings.gateway_mcp_url,
            "headers": {
                "Authorization": f"Bearer {user_token}",
                "X-Request-ID": request_id,
            },
            "timeout": self.settings.internal_timeout_seconds,
            "sse_read_timeout": self.settings.openai_timeout_seconds,
        }
        client = MultiServerMCPClient(
            {"tenant_gateway": connection},
            handle_tool_errors=True,
        )
        return await client.get_tools()
