"""
Tests for UI contract and API shape.

Covers:
- UI001: HTML page renders with required elements
- UI002: Tenant list endpoint returns expected shape
- UI003: Chat request shape is correct
- UI004: Sources render structure
- UI005: Tenant switch behavior
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch


@pytest_asyncio.fixture
async def client():
    """Create a test client with mocked startup."""
    # Mock the lifespan to avoid DB/index operations during tests
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_lifespan(app):
        yield

    with patch("app.main.lifespan", mock_lifespan):
        # Need to re-import to apply the patched lifespan
        import importlib
        import app.main
        importlib.reload(app.main)

        transport = ASGITransport(app=app.main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_ui_page_renders(client):
    """UI001: HTML page renders successfully."""
    response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")

    # Check required UI elements are present
    html = response.text
    assert "tenant-info" in html, "Should have tenant info display"
    assert "message-input" in html, "Should have message input"
    assert "send-btn" in html, "Should have send button"
    assert "chat-messages" in html, "Should have chat messages area"
    assert "new-session-btn" in html, "Should have new session button"
    assert "session-list" in html, "Should have a saved-session list"
    assert 'id="admin-tenant-section"' in html
    assert 'data-tenant-id="tenant-A"' in html
    assert 'data-tenant-id="tenant-B"' in html
    assert 'id="admin-readonly-note"' in html
    assert 'id="loading-indicator"' in html, "Should have a loading status"
    input_area = html[html.index('<div class="input-area">'):]
    assert input_area.index('id="loading-indicator"') < input_area.index(
        '<div class="input-wrapper">'
    ), "Loading status should sit directly above the question input container"
    assert 'role="status"' in input_area
    assert 'aria-live="polite"' in input_area
    assert "reindex-btn" in html, "Should have reindex button"
    assert (
        "Pooled Multi-Tenant Architecture RAG Chatbot" in html
        and "Simple Demo" in html
    ), "Should show the current login welcome message"
    assert (
        "Choose demo account credentials from the list below." in html
    ), "Should direct users to the demo accounts"
    assert (
        "<br><em>Can I pay with PayPal?</em>, or<br>"
        "<em>How many days do I have to return an item?</em>" in html
    ), "Should render the initial Tenant A examples on separate lines"
    assert "login-submit" in html, "Should apply the prominent login button treatment"
    assert (
        '<form id="login-form" class="login-form" method="post"' in html
    ), "Should never expose credentials through a native GET form submission"
    assert (
        'src="/static/app.js?v=' in html
    ), "Should cache-bust the JavaScript that owns authentication"


@pytest.mark.asyncio
async def test_tenant_list_endpoint_shape(client):
    """UI002: Tenant list endpoint returns expected shape."""
    with patch("app.api.tenants.list_tenants", new_callable=AsyncMock) as mock:
        from app.schemas import TenantResponse
        mock.return_value = [
            TenantResponse(
                tenant_id="tenant-A",
                tenant_name="Tenant A - Acme Payments",
                created_at="2026-07-11T00:00:00Z",
                metadata={"theme": "blue", "tier": "demo"},
            ),
        ]

        response = await client.get("/api/tenants")

    assert response.status_code == 200
    data = response.json()
    assert "tenants" in data
    assert len(data["tenants"]) > 0

    tenant = data["tenants"][0]
    assert "tenant_id" in tenant
    assert "tenant_name" in tenant
    assert "created_at" in tenant


@pytest.mark.asyncio
async def test_chat_without_token_is_rejected(client):
    """UI003: Chat request without a JWT token returns 401 Unauthorized."""
    response = await client.post(
        "/api/chat",
        json={"message": "Hello"},
    )

    # Without a token, the JWT dependency fires before body validation → 401
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_without_token_always_401(client):
    """Chat request without token returns 401 regardless of body content."""
    response = await client.post(
        "/api/chat",
        json={"tenant_id": "tenant-A", "message": ""},
    )

    # Auth fires before body validation
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_static_css_served(client):
    """Static CSS file is accessible."""
    response = await client.get("/static/styles.css")
    assert response.status_code == 200
    assert "text/css" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_static_js_served(client):
    """Static JS file is accessible."""
    response = await client.get("/static/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers.get("content-type", "")
    assert "setSources" in response.text
    assert "async function loadSessions()" in response.text
    assert "async function openSession(sessionId)" in response.text
    assert "async function deleteSavedSession(sessionId, deleteButton)" in response.text
    assert "Confirm delete" in response.text
    assert "`/api/sessions/${encodeURIComponent(sessionId)}`" in response.text
    assert "method: 'DELETE'" in response.text
    assert "sendBtn.innerHTML = '<span class=\"spinner\"></span>'" not in response.text
    assert "message.role === 'human'" in response.text
    assert (
        "Tenant A's basic knowledge base covers only" in response.text
    ), "Should render the Tenant A welcome copy after sign-in"
    assert (
        "Tenant B's basic knowledge base covers only" in response.text
    ), "Should render tenant-appropriate welcome copy for Tenant B"
    assert (
        "<br><em><strong>Can I pay with PayPal?</strong></em>" in response.text
        and "<br><em><strong>How many days do I have to return an item?</strong></em>"
        in response.text
    ), "Should preserve line breaks in the post-login Tenant A welcome copy"
    assert "example-chip" not in response.text
    assert "Double charge help" not in response.text
    assert "Refund policy" not in response.text
    assert "Welcome to Pooled Multi-Tenant Architecture RAG Chatbot Demo – Admin Account" in response.text
    assert "This is the demo administrator account" in response.text
    assert "async function selectAdminTenant(tenantId)" in response.text
    assert "/api/admin/tenants/${encodeURIComponent(state.selectedTenantId)}/sessions" in response.text
    assert "if (!isAdmin())" in response.text
