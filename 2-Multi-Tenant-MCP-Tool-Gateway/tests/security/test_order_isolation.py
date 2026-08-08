"""Orders capability, TVM, and key-prefix denial tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.shared.capability_tokens import (
    issue_store_credential,
    issue_tenant_capability,
    verify_tenant_capability,
)
from app.shared.claims import AuthenticationError, AuthorizationError
from app.targets.orders.service import QueryOrdersInput


def _alter_signature(token: str) -> str:
    header, payload, signature = token.split(".")
    index = len(signature) // 2
    replacement = "A" if signature[index] != "A" else "B"
    return f"{header}.{payload}.{signature[:index]}{replacement}{signature[index + 1 :]}"


@pytest.mark.asyncio
async def test_gateway_order_query_returns_only_authenticated_tenant(runtime) -> None:  # type: ignore[no-untyped-def]
    principal = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo")
    result = await runtime.gateway_router.query_orders(
        principal=principal,
        arguments=QueryOrdersInput(limit=20),
        request_id=str(uuid4()),
    )
    assert {record["order_id"][0] for record in result["records"]} == {"A"}


@pytest.mark.asyncio
async def test_tenant_a_store_credential_cannot_read_tenant_b_key(runtime) -> None:  # type: ignore[no-untyped-def]
    credential = issue_store_credential(
        runtime.gateway_authority,
        tenant_id="tenant-A",
        request_id=str(uuid4()),
        ttl_seconds=45,
    )
    with pytest.raises(AuthorizationError, match="outside"):
        await runtime.order_store.get_exact(
            credential=credential,
            key="tenant:tenant-B:orders:B-2001",
        )


@pytest.mark.asyncio
async def test_expired_or_modified_store_credential_is_rejected(runtime) -> None:  # type: ignore[no-untyped-def]
    request_id = str(uuid4())
    expired = issue_store_credential(
        runtime.gateway_authority,
        tenant_id="tenant-A",
        request_id=request_id,
        ttl_seconds=-1,
    )
    with pytest.raises(AuthenticationError):
        await runtime.order_store.get_exact(
            credential=expired,
            key="tenant:tenant-A:orders:A-1001",
        )
    current = issue_store_credential(
        runtime.gateway_authority,
        tenant_id="tenant-A",
        request_id=request_id,
        ttl_seconds=45,
    )
    with pytest.raises(AuthenticationError):
        await runtime.order_store.get_exact(
            credential=_alter_signature(current),
            key="tenant:tenant-A:orders:A-1001",
        )


def test_modified_or_expired_capability_is_rejected(runtime) -> None:  # type: ignore[no-untyped-def]
    request_id = str(uuid4())
    capability = issue_tenant_capability(
        runtime.gateway_authority,
        tenant_id="tenant-A",
        tool="query_orders",
        request_id=request_id,
        ttl_seconds=60,
    )
    altered = _alter_signature(capability)
    with pytest.raises(AuthenticationError):
        verify_tenant_capability(
            runtime.gateway_authority,
            altered,
            audience="orders-target",
            expected_tool="query_orders",
        )
    expired = runtime.gateway_authority.issue(
        subject="mcp-gateway",
        audience=["orders-target", "local-tvm"],
        ttl_seconds=-1,
        claims={
            "tenant_id": "tenant-A",
            "tool": "query_orders",
            "request_id": request_id,
        },
    )
    with pytest.raises(AuthenticationError):
        verify_tenant_capability(
            runtime.gateway_authority,
            expired,
            audience="orders-target",
            expected_tool="query_orders",
        )


def test_tvm_rejects_request_id_mismatch(runtime) -> None:  # type: ignore[no-untyped-def]
    capability = issue_tenant_capability(
        runtime.gateway_authority,
        tenant_id="tenant-A",
        tool="query_orders",
        request_id=str(uuid4()),
        ttl_seconds=60,
    )
    service_token = runtime.service_tokens.get(
        client_id=runtime.settings.orders_service_client_id,
        client_secret=runtime.secrets.orders_service_client_secret,
        audience="local-tvm",
        scope="credentials.issue",
    )
    with pytest.raises(AuthorizationError, match="identifier"):
        runtime.tvm.issue_order_store_credential(
            service_token=service_token,
            capability=capability,
            request_id=str(uuid4()),
        )
