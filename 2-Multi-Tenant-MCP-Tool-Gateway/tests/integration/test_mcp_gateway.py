"""Streamable HTTP MCP protocol, schema, auth, and interceptor integration tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import mcp_headers, mcp_request


def test_initialize_ping_and_tools_list(client: TestClient, runtime) -> None:  # type: ignore[no-untyped-def]
    token = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo").token
    initialize = mcp_request(
        client,
        token=token,
        method="initialize",
        params={
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1"},
        },
    )
    assert initialize["result"]["serverInfo"]["name"] == "multi_tenant_gateway_mcp"
    ping = mcp_request(client, token=token, method="ping", params={})
    assert ping["result"] == {}
    listing = mcp_request(client, token=token, method="tools/list", params={})
    tools = listing["result"]["tools"]
    assert {tool["name"] for tool in tools} == {"query_orders", "query_properties"}
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["additionalProperties"] is False
        assert "tenant_id" not in schema["properties"]
        assert "x-tenant-id" not in schema["properties"]


def test_missing_gateway_bearer_is_401(client: TestClient) -> None:
    response = client.post(
        "/mcp/",
        headers={"Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 401


def test_forged_tenant_header_is_stripped_and_audited(
    client: TestClient,
    runtime,
) -> None:  # type: ignore[no-untyped-def]
    request_id = "22222222-2222-4222-8222-222222222222"
    token = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo").token
    result = mcp_request(
        client,
        token=token,
        method="tools/call",
        params={"name": "query_orders", "arguments": {"limit": 20}},
        request_id=request_id,
        extra_headers={"X-Tenant-ID": "tenant-B", "X-User-Token": "forged"},
    )
    structured = result["result"]["structuredContent"]
    assert {record["order_id"][0] for record in structured["records"]} == {"A"}
    events = runtime.audit.for_request(request_id)
    assert any(event["action"] == "strip_untrusted_context" for event in events)


def test_unknown_or_extra_tool_arguments_fail_closed(client: TestClient, runtime) -> None:  # type: ignore[no-untyped-def]
    token = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo").token
    unknown = mcp_request(
        client,
        token=token,
        method="tools/call",
        params={"name": "delete_orders", "arguments": {}},
    )
    assert unknown["result"]["isError"] is True
    extra = mcp_request(
        client,
        token=token,
        method="tools/call",
        params={
            "name": "query_orders",
            "arguments": {"limit": 1, "tenant_id": "tenant-B"},
        },
    )
    assert extra["result"]["isError"] is True


def test_properties_target_requires_both_credentials(client: TestClient, runtime) -> None:  # type: ignore[no-untyped-def]
    service = runtime.service_tokens.get(
        client_id=runtime.settings.gateway_service_client_id,
        client_secret=runtime.secrets.gateway_service_client_secret,
        audience="properties-mcp",
        scope="mcp.tools.call",
    )
    missing_user = client.post(
        "/internal/mcp/properties/",
        headers=mcp_headers(service),
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert missing_user.status_code == 401
    user = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo").token
    result = mcp_request(
        client,
        token=service,
        method="tools/call",
        params={"name": "query_properties", "arguments": {"limit": 20}},
        extra_headers={"X-User-Token": user},
        path="/internal/mcp/properties/",
    )
    records = result["result"]["structuredContent"]["records"]
    assert {record["property_id"][:2] for record in records} == {"PA"}


def test_concurrent_mcp_principals_do_not_share_authorization(
    client: TestClient,
    runtime,
) -> None:  # type: ignore[no-untyped-def]
    alice = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo").token
    bob = runtime.identity.authenticate_user("bob@tenant-b.demo", "bob-demo").token

    def call(index: int) -> tuple[str, set[str]]:
        expected = "A" if index % 2 == 0 else "B"
        result = mcp_request(
            client,
            token=alice if index % 2 == 0 else bob,
            method="tools/call",
            params={"name": "query_orders", "arguments": {"limit": 20}},
            request_id=str(uuid4()),
        )["result"]["structuredContent"]
        return expected, {record["order_id"][0] for record in result["records"]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(call, index) for index in range(20)]
    for future in futures:
        expected, observed = future.result()
        assert observed == {expected}
