"""Isolated fixtures with injected model doubles for the complete ASGI application."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lifespan import RuntimeDependencies
from app.main import create_app
from app.settings import Settings
from scripts.test_doubles import DeterministicChatBackend, DeterministicEmbeddings


@pytest.fixture(scope="session")
def test_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """Use generated state outside the source tree and never read a developer ``.env``."""

    root = tmp_path_factory.mktemp("runtime")
    return Settings(
        _env_file=None,
        testing=True,
        openai_api_key="",
        sqlite_path=root / "demo.db",
        identity_private_key_path=root / "keys" / "identity_private.pem",
        identity_public_key_path=root / "keys" / "identity_public.pem",
        gateway_capability_private_key_path=root / "keys" / "gateway_private.pem",
        gateway_capability_public_key_path=root / "keys" / "gateway_public.pem",
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def runtime_dependencies() -> RuntimeDependencies:
    """Inject deterministic model collaborators; never select them through settings."""

    return RuntimeDependencies(
        embeddings=DeterministicEmbeddings(),
        chat_backend=DeterministicChatBackend(),
    )


@pytest.fixture(scope="session")
def application(
    test_settings: Settings,
    runtime_dependencies: RuntimeDependencies,
) -> FastAPI:
    """Construct one application so its mounted MCP managers have one lifecycle."""

    return create_app(test_settings, runtime_dependencies=runtime_dependencies)


@pytest.fixture(scope="session")
def app_client(application: FastAPI) -> Iterator[TestClient]:
    """Run the real lifespan and both mounted FastMCP session managers."""

    with TestClient(application, base_url="http://localhost:8000") as client:
        yield client


@pytest.fixture
def client(app_client: TestClient) -> Iterator[TestClient]:
    """Clear browser cookies between HTTP tests while retaining seeded runtime state."""

    app_client.cookies.clear()
    yield app_client
    app_client.cookies.clear()


@pytest.fixture
def runtime(application: FastAPI) -> Any:
    """Return initialized application dependencies for focused service tests."""

    return application.state.runtime


def login(client: TestClient, username: str, password: str) -> dict[str, Any]:
    """Authenticate one seeded user through the browser contract."""

    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["identity"]


def mcp_headers(
    token: str,
    request_id: str = "11111111-1111-4111-8111-111111111111",
) -> dict[str, str]:
    """Return protocol and auth headers for stateless Streamable HTTP calls."""

    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
        "X-Request-ID": request_id,
    }


def mcp_request(
    client: TestClient,
    *,
    token: str,
    method: str,
    params: dict[str, Any],
    request_id: str = "11111111-1111-4111-8111-111111111111",
    extra_headers: dict[str, str] | None = None,
    path: str = "/mcp/",
) -> dict[str, Any]:
    """Send one stateless JSON-RPC request to a mounted MCP application."""

    headers = mcp_headers(token, request_id)
    headers.update(extra_headers or {})
    response = client.post(
        path,
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )
    assert response.status_code == 200, response.text
    return response.json()
