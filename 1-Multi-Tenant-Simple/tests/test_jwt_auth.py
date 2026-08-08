"""
Tests for JWT authentication flow.

Covers:
- JA001: Valid credentials return a signed JWT
- JA002: Invalid credentials return 401
- JA003: POST /api/chat with a valid token succeeds (passes auth layer)
- JA004: POST /api/chat without a token returns 401
- JA005: POST /api/chat with an invalid token returns 401
- JA006: POST /api/chat with an expired token returns 401
- JA007: Token contains correct tenant_id claim
- JA008: Admin endpoint accessible with admin token, blocked for user token
"""

from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.schemas import TenantResponse


# ──────────────────────────────────────────────
# Test Fixtures
# ──────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    """Create a test client with mocked startup."""
    @asynccontextmanager
    async def mock_lifespan(app):
        yield

    with patch("app.main.lifespan", mock_lifespan):
        import importlib
        import app.main
        importlib.reload(app.main)

        transport = ASGITransport(app=app.main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _get_token(client, username: str, password: str) -> dict:
    """Helper: perform a login and return the token response dict."""
    response = await client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return response


# ──────────────────────────────────────────────
# JA001 – JA002: Login endpoint
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_login_returns_token(client):
    """JA001: Valid credentials return an access_token and tenant_id."""
    resp = await _get_token(client, "user-a", "password-a")
    assert resp.status_code == 200

    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["tenant_id"] == "tenant-A"
    assert data["role"] == "user"
    # Token should be a non-empty string
    assert len(data["access_token"]) > 20


@pytest.mark.asyncio
async def test_invalid_credentials_returns_401(client):
    """JA002: Wrong password returns 401."""
    resp = await _get_token(client, "user-a", "wrong-password")
    assert resp.status_code == 401
    assert "Incorrect" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_user_returns_401(client):
    """JA002b: Unknown username returns 401."""
    resp = await _get_token(client, "no-such-user", "any-password")
    assert resp.status_code == 401


# ──────────────────────────────────────────────
# JA007: Token claims
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_contains_correct_tenant_id(client):
    """JA007: Decoded JWT contains correct tenant_id claim for each user."""
    from app.config import settings

    for username, password, expected_tenant in [
        ("user-a", "password-a", "tenant-A"),
        ("user-b", "password-b", "tenant-B"),
    ]:
        resp = await _get_token(client, username, password)
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        # Decode and verify claims directly (bypasses FastAPI)
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        assert payload["tenant_id"] == expected_tenant
        assert payload["sub"] == username
        assert "exp" in payload


# ──────────────────────────────────────────────
# JA003 – JA006: Protected endpoint
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_without_token_returns_401(client):
    """JA004: POST /api/chat without token returns 401."""
    response = await client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_with_invalid_token_returns_401(client):
    """JA005: POST /api/chat with a garbage token returns 401."""
    response = await client.post(
        "/api/chat",
        headers={"Authorization": "Bearer this.is.not.a.valid.token"},
        json={"message": "Hello"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_with_expired_token_returns_401(client):
    """JA006: POST /api/chat with an expired token returns 401."""
    from app.services.auth import create_access_token

    # Create a token that expired 10 seconds ago
    expired_token = create_access_token(
        username="user-a",
        tenant_id="tenant-A",
        role="user",
        expires_delta=timedelta(seconds=-10),
    )

    response = await client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {expired_token}"},
        json={"message": "Hello"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_with_valid_token_passes_auth(client):
    """
    JA003: POST /api/chat with a valid token passes the auth layer.

    We don't call the full RAG pipeline — we mock validate_tenant and
    stream_rag_chain to isolate the auth check.
    """
    login_resp = await _get_token(client, "user-a", "password-a")
    token = login_resp.json()["access_token"]

    # Mock at the service layer so we don't need the real DB or OpenAI
    with (
        patch(
            "app.api.chat.validate_tenant",
            new_callable=AsyncMock,
            return_value=TenantResponse(
                tenant_id="tenant-A",
                tenant_name="Tenant A - Acme Payments",
                created_at="2026-01-01T00:00:00Z",
            ),
        ),
        patch("app.services.chat.load_recent_messages", return_value=[]),
        patch("app.services.chat.create_session", new_callable=AsyncMock, return_value="sess-123"),
        patch("app.services.chat.get_session", new_callable=AsyncMock, return_value=None),
        patch(
            "app.rag.chain.stream_rag_chain",
        ) as mock_stream,
    ):
        # Simulate a minimal SSE stream
        async def fake_stream(*args, **kwargs):
            yield ("setup", {"sources": []})
            yield ("token", "Hello!")
            yield ("done", {"latency_ms": 10, "answer": "Hello!"})

        mock_stream.return_value = fake_stream()

        with (
            patch("app.services.chat.save_messages"),
            patch("app.services.chat.update_session_timestamp", new_callable=AsyncMock),
            patch("app.services.telemetry.log_rag_event", new_callable=AsyncMock),
        ):
            response = await client.post(
                "/api/chat",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": "What is the refund policy?"},
            )

    # Auth layer passed (200 or streaming 200)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_session_detail_hides_foreign_tenant_session(client):
    """A valid Tenant A token cannot inspect a Tenant B session by ID."""

    login_resp = await _get_token(client, "user-a", "password-a")
    token = login_resp.json()["access_token"]
    with patch(
        "app.api.chat.get_session",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(tenant_id="tenant-B"),
    ):
        response = await client.get(
            "/api/sessions/session-from-b",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_session_list_is_scoped_to_authenticated_tenant(client):
    """Saved-session listing uses the tenant claim from the JWT."""

    login_resp = await _get_token(client, "user-a", "password-a")
    token = login_resp.json()["access_token"]
    tenant_session = SimpleNamespace(
        session_id="session-from-a",
        tenant_id="tenant-A",
        title="Tenant A chat",
        created_at="2026-07-25T08:00:00+00:00",
        updated_at="2026-07-25T09:00:00+00:00",
    )

    with (
        patch(
            "app.api.chat.validate_tenant",
            new_callable=AsyncMock,
            return_value=TenantResponse(
                tenant_id="tenant-A",
                tenant_name="Tenant A - Acme Payments",
                created_at="2026-01-01T00:00:00Z",
            ),
        ),
        patch(
            "app.api.chat.list_sessions",
            new_callable=AsyncMock,
            return_value=[tenant_session],
        ) as mock_list_sessions,
    ):
        response = await client.get(
            "/api/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    mock_list_sessions.assert_awaited_once_with("tenant-A")
    assert response.json()["sessions"][0]["tenant_id"] == "tenant-A"


@pytest.mark.asyncio
async def test_session_delete_is_scoped_to_authenticated_tenant(client):
    """Deleting a session passes the JWT tenant to the deletion service."""

    login_resp = await _get_token(client, "user-a", "password-a")
    token = login_resp.json()["access_token"]

    with patch(
        "app.api.chat.delete_session",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_delete_session:
        response = await client.delete(
            "/api/sessions/session-from-a",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    mock_delete_session.assert_awaited_once_with("session-from-a", "tenant-A")
    assert response.json() == {
        "session_id": "session-from-a",
        "status": "deleted",
    }


@pytest.mark.asyncio
async def test_session_delete_hides_foreign_or_missing_session(client):
    """Foreign and missing sessions share the same not-found response."""

    login_resp = await _get_token(client, "user-a", "password-a")
    token = login_resp.json()["access_token"]

    with patch(
        "app.api.chat.delete_session",
        new_callable=AsyncMock,
        return_value=False,
    ):
        response = await client.delete(
            "/api/sessions/session-from-b",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


# ──────────────────────────────────────────────
# JA008: Admin-only endpoint
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reindex_blocked_for_regular_user(client):
    """JA008a: Regular user cannot access POST /api/admin/reindex (403)."""
    login_resp = await _get_token(client, "user-a", "password-a")
    token = login_resp.json()["access_token"]

    response = await client.post(
        "/api/admin/reindex",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reindex_allowed_for_admin(client):
    """JA008b: Admin user can access POST /api/admin/reindex."""
    login_resp = await _get_token(client, "admin", "admin-secret")
    token = login_resp.json()["access_token"]

    with (
        patch("app.api.admin.list_tenants", new_callable=AsyncMock, return_value=[]),
        patch("app.api.admin.index_all_tenants", new_callable=AsyncMock, return_value=[]),
    ):
        response = await client.post(
            "/api/admin/reindex",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

    # Admin can access the endpoint (200 or possibly 500 from mocked internals)
    assert response.status_code in (200, 500)
    assert response.status_code != 401
    assert response.status_code != 403


@pytest.mark.asyncio
async def test_admin_session_browser_blocked_for_regular_user(client):
    """Tenant users cannot call the cross-tenant administrator session API."""
    login_resp = await _get_token(client, "user-a", "password-a")
    token = login_resp.json()["access_token"]

    response = await client.get(
        "/api/admin/tenants/tenant-B/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin role required for this operation."


@pytest.mark.asyncio
async def test_admin_can_list_selected_tenant_sessions(client):
    """An admin can explicitly browse sessions from either selected tenant."""
    login_resp = await _get_token(client, "admin", "admin-secret")
    login_data = login_resp.json()
    assert login_data["role"] == "admin"
    token = login_data["access_token"]
    tenant_session = SimpleNamespace(
        session_id="session-from-b",
        tenant_id="tenant-B",
        title="Tenant B support chat",
        created_at="2026-07-25T08:00:00+00:00",
        updated_at="2026-07-25T09:00:00+00:00",
    )

    with (
        patch(
            "app.api.admin.validate_tenant",
            new_callable=AsyncMock,
            return_value=TenantResponse(
                tenant_id="tenant-B",
                tenant_name="Tenant B - Beta Devices",
                created_at="2026-01-01T00:00:00Z",
            ),
        ) as mock_validate_tenant,
        patch(
            "app.api.admin.list_sessions",
            new_callable=AsyncMock,
            return_value=[tenant_session],
        ) as mock_list_sessions,
    ):
        response = await client.get(
            "/api/admin/tenants/tenant-B/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    mock_validate_tenant.assert_awaited_once_with("tenant-B")
    mock_list_sessions.assert_awaited_once_with("tenant-B")
    assert response.json()["sessions"] == [
        {
            "session_id": "session-from-b",
            "tenant_id": "tenant-B",
            "title": "Tenant B support chat",
            "created_at": "2026-07-25T08:00:00+00:00",
            "updated_at": "2026-07-25T09:00:00+00:00",
        }
    ]


@pytest.mark.asyncio
async def test_admin_session_detail_enforces_selected_tenant_scope(client):
    """A session cannot be opened through a mismatched admin tenant path."""
    login_resp = await _get_token(client, "admin", "admin-secret")
    token = login_resp.json()["access_token"]

    with (
        patch(
            "app.api.admin.validate_tenant",
            new_callable=AsyncMock,
            return_value=TenantResponse(
                tenant_id="tenant-A",
                tenant_name="Tenant A - Acme Payments",
                created_at="2026-01-01T00:00:00Z",
            ),
        ),
        patch(
            "app.api.admin.get_session",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(tenant_id="tenant-B"),
        ),
        patch("app.api.admin.load_recent_messages") as mock_load_messages,
    ):
        response = await client.get(
            "/api/admin/tenants/tenant-A/sessions/session-from-b",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"
    mock_load_messages.assert_not_called()
