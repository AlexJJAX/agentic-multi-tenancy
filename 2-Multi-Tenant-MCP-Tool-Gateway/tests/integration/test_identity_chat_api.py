"""Browser identity, cookie, chat, and session boundary integration tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import login


@pytest.mark.parametrize(
    ("username", "password"),
    (
        ("alice@tenant-a.demo", "alice-demo"),
        ("bob@tenant-b.demo", "bob-demo"),
    ),
)
def test_simple_opening_greeting_is_tenant_independent(
    client: TestClient,
    username: str,
    password: str,
) -> None:
    login(client, username, password)
    session = client.post("/api/sessions", json={}).json()["session_id"]

    response = client.post(
        "/api/chat",
        json={"session_id": session, "message": "Hi"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Hi — how can I help you today?"
    assert response.json()["sources"] == []
    assert response.json()["trace"]["tools"] == []


def test_login_sets_httponly_cookie_and_me_has_immutable_tenant(client: TestClient) -> None:
    identity = login(client, "alice@tenant-a.demo", "alice-demo")
    assert identity["tenant_id"] == "tenant-A"
    cookie = client.cookies.get("mt_session")
    assert cookie
    set_cookie = (
        client.post(
            "/auth/login",
            json={"username": "alice@tenant-a.demo", "password": "alice-demo"},
        )
        .headers["set-cookie"]
        .lower()
    )
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert client.get("/api/me").json()["tenant_id"] == "tenant-A"


def test_logout_invalidates_session(client: TestClient) -> None:
    login(client, "alice@tenant-a.demo", "alice-demo")
    assert client.get("/api/me").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_cross_tenant_session_history_is_not_visible(client: TestClient) -> None:
    login(client, "alice@tenant-a.demo", "alice-demo")
    session = client.post("/api/sessions", json={}).json()["session_id"]
    answer = client.post(
        "/api/chat",
        json={"session_id": session, "message": "How long does a card refund take?"},
    )
    assert answer.status_code == 200
    sources = answer.json()["sources"]
    assert "knowledge/tenant-A.md" in str(sources)
    assert all(source["excerpt"] for source in sources if source["type"] == "document")
    assert "[knowledge/" not in answer.json()["answer"]
    login(client, "bob@tenant-b.demo", "bob-demo")
    foreign = client.get(f"/api/sessions/{session}/messages")
    assert foreign.status_code == 404
    assert session not in {item["session_id"] for item in client.get("/api/sessions").json()}


def test_session_history_removes_legacy_inline_citations(
    client: TestClient,
    runtime,  # type: ignore[no-untyped-def]
) -> None:
    identity = login(client, "bob@tenant-b.demo", "bob-demo")
    session = client.post("/api/sessions", json={}).json()["session_id"]
    sources = [
        {
            "type": "document",
            "source": "knowledge/tenant-B.md",
            "section": "Factory reset",
            "chunk_index": 1,
        }
    ]
    runtime.history.append_exchange(
        tenant_id=identity["tenant_id"],
        user_id=identity["user_id"],
        session_id=session,
        user_message="How do I reset the device?",
        assistant_message=(
            "Hold the reset button for 15 seconds [source — Factory reset]."
        ),
        assistant_metadata={"sources": sources},
    )

    history = client.get(f"/api/sessions/{session}/messages").json()
    assistant = next(item for item in history if item["role"] == "assistant")
    assert assistant["content"] == "Hold the reset button for 15 seconds."
    assert json.loads(assistant["metadata_json"])["sources"] == sources


def test_tenant_a_colleagues_cannot_see_each_others_sessions(client: TestClient) -> None:
    login(client, "alice@tenant-a.demo", "alice-demo")
    alice_session = client.post("/api/sessions", json={}).json()["session_id"]

    carol_identity = login(client, "carol@tenant-a.demo", "carol-demo")
    assert carol_identity["tenant_id"] == "tenant-A"
    assert alice_session not in {
        item["session_id"] for item in client.get("/api/sessions").json()
    }
    assert client.get(f"/api/sessions/{alice_session}/messages").status_code == 404
    carol_session = client.post("/api/sessions", json={}).json()["session_id"]

    login(client, "alice@tenant-a.demo", "alice-demo")
    alice_sessions = {item["session_id"] for item in client.get("/api/sessions").json()}
    assert alice_session in alice_sessions
    assert carol_session not in alice_sessions
    assert client.get(f"/api/sessions/{carol_session}/messages").status_code == 404


def test_tenant_b_colleagues_cannot_see_each_others_sessions(client: TestClient) -> None:
    login(client, "bob@tenant-b.demo", "bob-demo")
    bob_session = client.post("/api/sessions", json={}).json()["session_id"]

    jake_identity = login(client, "jake@tenant-b.demo", "jake-demo")
    assert jake_identity["tenant_id"] == "tenant-B"
    assert bob_session not in {
        item["session_id"] for item in client.get("/api/sessions").json()
    }
    assert client.get(f"/api/sessions/{bob_session}/messages").status_code == 404
    jake_session = client.post("/api/sessions", json={}).json()["session_id"]

    login(client, "bob@tenant-b.demo", "bob-demo")
    bob_sessions = {item["session_id"] for item in client.get("/api/sessions").json()}
    assert bob_session in bob_sessions
    assert jake_session not in bob_sessions
    assert client.get(f"/api/sessions/{jake_session}/messages").status_code == 404


def test_session_delete_removes_owned_session_and_messages(
    client: TestClient,
    runtime,  # type: ignore[no-untyped-def]
) -> None:
    login(client, "alice@tenant-a.demo", "alice-demo")
    session = client.post("/api/sessions", json={}).json()["session_id"]
    response = client.post(
        "/api/chat",
        json={"session_id": session, "message": "How long does a card refund take?"},
    )
    assert response.status_code == 200

    deleted = client.delete(f"/api/sessions/{session}")
    assert deleted.status_code == 204
    assert session not in {item["session_id"] for item in client.get("/api/sessions").json()}
    assert client.get(f"/api/sessions/{session}/messages").status_code == 404
    with runtime.store.connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM chat_messages WHERE session_id = ?", (session,)
        ).fetchone()[0] == 0


def test_cross_tenant_session_delete_is_denied(client: TestClient) -> None:
    login(client, "alice@tenant-a.demo", "alice-demo")
    session = client.post("/api/sessions", json={}).json()["session_id"]
    client.post(
        "/api/chat",
        json={"session_id": session, "message": "How long does a card refund take?"},
    )

    login(client, "bob@tenant-b.demo", "bob-demo")
    assert client.delete(f"/api/sessions/{session}").status_code == 404

    login(client, "alice@tenant-a.demo", "alice-demo")
    assert client.get(f"/api/sessions/{session}/messages").status_code == 200
    assert session in {item["session_id"] for item in client.get("/api/sessions").json()}


def test_chat_routes_to_orders_and_properties_without_tenant_input(client: TestClient) -> None:
    login(client, "alice@tenant-a.demo", "alice-demo")
    session = client.post("/api/sessions", json={}).json()["session_id"]
    order = client.post(
        "/api/chat",
        json={"session_id": session, "message": "What is the status of order A-1002?"},
    ).json()
    assert order["trace"]["tools"] == ["query_orders"]
    assert "refund_pending" in order["answer"]
    properties = client.post(
        "/api/chat",
        json={"session_id": session, "message": "Show my visible properties."},
    ).json()
    assert properties["trace"]["tools"] == ["query_properties"]
    assert "PA-101" in properties["answer"]
    assert "PB-201" not in properties["answer"]


def test_request_body_cannot_supply_tenant(client: TestClient) -> None:
    login(client, "alice@tenant-a.demo", "alice-demo")
    response = client.post("/api/sessions", json={"tenant_id": "tenant-B"})
    assert response.status_code == 422


def test_streaming_chat_emits_route_tokens_and_done_metadata(client: TestClient) -> None:
    """The SSE contract exposes safe phases and text without tenant controls."""

    login(client, "alice@tenant-a.demo", "alice-demo")
    session = client.post("/api/sessions", json={}).json()["session_id"]
    response = client.post(
        "/api/chat/stream",
        json={"session_id": session, "message": "What is the status of order A-1001?"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: phase" in response.text
    assert "event: token" in response.text
    assert "event: done" in response.text
    assert "A-1001" in response.text
    assert "B-2001" not in response.text
    assert "[knowledge/" not in response.text
