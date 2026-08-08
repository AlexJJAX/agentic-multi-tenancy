"""Properties dual-token, view, authorizer, and concurrency tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.shared.claims import AuthenticationError
from app.targets.properties.service import QueryPropertiesInput


def _service_token(runtime) -> str:  # type: ignore[no-untyped-def]
    return runtime.service_tokens.get(
        client_id=runtime.settings.gateway_service_client_id,
        client_secret=runtime.secrets.gateway_service_client_secret,
        audience="properties-mcp",
        scope="mcp.tools.call",
    )


def test_valid_service_plus_user_context_returns_only_tenant_a(runtime) -> None:  # type: ignore[no-untyped-def]
    alice = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo")
    records = runtime.properties_target.query(
        service_token=_service_token(runtime),
        user_token=alice.token,
        arguments=QueryPropertiesInput(limit=20),
    )
    assert {record["property_id"][:2] for record in records} == {"PA"}


def test_user_token_is_rejected_as_primary_authorization(runtime) -> None:  # type: ignore[no-untyped-def]
    alice = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo")
    with pytest.raises(AuthenticationError):
        runtime.properties_target.query(
            service_token=alice.token,
            user_token=alice.token,
            arguments=QueryPropertiesInput(limit=20),
        )


def test_wrong_service_audience_is_rejected(runtime) -> None:  # type: ignore[no-untyped-def]
    alice = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo")
    orders_token = runtime.service_tokens.get(
        client_id=runtime.settings.gateway_service_client_id,
        client_secret=runtime.secrets.gateway_service_client_secret,
        audience="orders-target",
        scope="tools.invoke",
    )
    with pytest.raises(AuthenticationError):
        runtime.properties_target.query(
            service_token=orders_token,
            user_token=alice.token,
            arguments=QueryPropertiesInput(limit=20),
        )


def test_direct_table_read_is_denied_and_context_is_disposable(runtime) -> None:  # type: ignore[no-untyped-def]
    assert runtime.property_store.direct_read_denied("tenant-A")
    assert not runtime.property_store.new_connection_has_tenant_context()


def test_concurrent_property_calls_do_not_cross_contaminate(runtime) -> None:  # type: ignore[no-untyped-def]
    alice = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo")
    bob = runtime.identity.authenticate_user("bob@tenant-b.demo", "bob-demo")
    service_token = _service_token(runtime)

    def query(user_token: str) -> list[str]:
        records = runtime.properties_target.query(
            service_token=service_token,
            user_token=user_token,
            arguments=QueryPropertiesInput(limit=20),
        )
        return [record["property_id"] for record in records]

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(query, alice.token if index % 2 == 0 else bob.token) for index in range(30)
        ]
    for index, future in enumerate(futures):
        expected = "PA" if index % 2 == 0 else "PB"
        assert {value[:2] for value in future.result()} == {expected}
