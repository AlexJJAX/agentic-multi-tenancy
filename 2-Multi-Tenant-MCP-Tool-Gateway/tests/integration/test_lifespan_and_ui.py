"""Lifecycle readiness, idempotency, and browser-contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.lifespan import RuntimeDependencies, build_runtime
from app.settings import Settings
from scripts.test_doubles import DeterministicEmbeddings


def test_health_and_full_readiness(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready").json()
    assert ready["status"] == "ready"
    assert all(ready["checks"].values())


def test_runtime_uses_explicitly_injected_model_doubles(
    runtime,  # type: ignore[no-untyped-def]
    runtime_dependencies,  # type: ignore[no-untyped-def]
) -> None:
    assert runtime.rag.embeddings is runtime_dependencies.embeddings
    assert runtime.chat.response_backend is runtime_dependencies.chat_backend


def test_repeated_migration_and_seed_do_not_duplicate_rows(runtime) -> None:  # type: ignore[no-untyped-def]
    runtime.store.migrate()
    runtime.store.seed()
    runtime.store.seed()
    with runtime.store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM tenants").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 4
        assert connection.execute("SELECT count(*) FROM properties").fetchone()[0] == 6


def test_live_mode_requires_openai_key(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        testing=False,
        openai_api_key="",
        sqlite_path=tmp_path / "demo.db",
    )
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        settings.validate_runtime_requirements()


def test_testing_flag_cannot_bypass_openai_key_requirement() -> None:
    settings = Settings(_env_file=None, testing=True, openai_api_key="")
    with pytest.raises(RuntimeError, match="runtime always uses live OpenAI models"):
        settings.validate_runtime_requirements()


@pytest.mark.asyncio
async def test_partial_model_injection_still_requires_openai_key(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="",
        sqlite_path=tmp_path / "demo.db",
    )
    dependencies = RuntimeDependencies(embeddings=DeterministicEmbeddings())
    with pytest.raises(RuntimeError, match="runtime always uses live OpenAI models"):
        await build_runtime(settings, dependencies)


def test_ui_has_no_tenant_selector_or_browser_token_storage(client: TestClient) -> None:
    html = client.get("/").text
    script = client.get("/static/app.js").text
    assert "verified account sets the data boundary" in html.lower()
    assert 'name="tenant_id"' not in html
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert 'id="message-input"' in html
    assert "prefers-reduced-motion" in client.get("/static/styles.css").text
    assert 'value="alice-demo"' not in html
    accounts = (
        "alice@tenant-a.demo",
        "carol@tenant-a.demo",
        "bob@tenant-b.demo",
        "jake@tenant-b.demo",
    )
    assert [html.index(account) for account in accounts] == sorted(
        html.index(account) for account in accounts
    )
    for account, password in zip(
        accounts,
        ("alice-demo", "carol-demo", "bob-demo", "jake-demo"),
        strict=True,
    ):
        assert f'"{account}": "{password}"' in script
    assert "usernameSelect.addEventListener(\"change\", fillDemoPassword);" in script
    assert "fillDemoPassword();" in script


def test_ui_exposes_inline_session_delete_confirmation(client: TestClient) -> None:
    script = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text
    assert 'method: "DELETE"' in script
    assert 'deleteButton.textContent = isConfirming ? "Confirm" : "Delete";' in script
    assert "encodeURIComponent(session.session_id)" in script
    assert ".session-delete.confirming" in styles


def test_trust_rail_uses_distinct_bootstrap_icons_for_each_state(
    client: TestClient,
) -> None:
    html = client.get("/").text
    script = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    icon_pairs = (
        ("identity", "people-fill", "person-bounding-box"),
        ("rag", "collection", "bullseye"),
        ("gateway", "arrow-left-right", "shield-lock-fill"),
        ("target", "patch-question", "crosshair"),
    )
    for node, default_icon, complete_icon in icon_pairs:
        node_start = html.index(f'data-node="{node}"')
        node_end = html.index("</li>", node_start)
        node_html = html[node_start:node_end]
        assert f"bi-{default_icon}" in node_html
        assert f"bi-{complete_icon}" in node_html
        assert 'class="trust-node-description"' in node_html
        assert node_html.index(f"bi-{default_icon}") < node_html.index(
            f"bi-{complete_icon}"
        )

    assert "color: var(--danger);" in styles
    assert ".trust-rail li.active .trust-node-icon { color: var(--safe); }" in styles
    assert ".trust-icon-complete { opacity: 0;" in styles
    assert ".trust-rail li.active .trust-icon-complete { opacity: 1;" in styles
    assert "--trust-icon-duration: 240ms;" in styles
    assert ".trust-node-description {" in styles
    assert ".trust-rail li.active .trust-node-description {" in styles
    assert styles.count(
        "transition-delay: var(--trust-icon-duration), "
        "var(--trust-icon-duration), var(--trust-icon-duration);"
    ) == 1

    submit_start = script.index('chatForm.addEventListener("submit"')
    submit_end = script.index("\n});", submit_start)
    submit_block = script[submit_start:submit_end]
    assert submit_block.index("resetTrustRail();") < submit_block.index("streamChat(")


def test_ui_renders_response_sources_in_collapsible_panels(client: TestClient) -> None:
    script = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    for statement in (
        'panel.className = "message-sources";',
        "panel.open = true;",
        'summary.className = "sources-summary";',
        'name.textContent = view.title;',
        'excerpt.textContent = view.excerpt;',
        "renderSources(assistantContent.parentElement, sources);",
        "addMessage(item.role, item.content, historySources(item));",
        "JSON.parse(item.metadata_json)",
    ):
        assert statement in script

    for selector in (
        ".message-sources {",
        ".sources-summary {",
        ".sources-list {",
        ".source-reference {",
        ".message .source-excerpt {",
    ):
        assert selector in styles


def test_empty_conversation_uses_the_tenant_placeholder_until_next_message(
    client: TestClient,
) -> None:
    script = client.get("/static/app.js").text
    delete_start = script.index("async function handleSessionDelete")
    delete_end = script.index("\n}\n\nfunction updateTrace", delete_start)
    delete_block = script[delete_start:delete_end]

    assert "await createSession();" not in delete_block
    assert 'emptyState.textContent = "No saved sessions.";' in script
    assert 'if (!currentSession) await createSession();' in script
    assert "showTenantPlaceholder();" in delete_block

    for message in (
        "Hi there! I’m your payment and product support assistant. "
        "Ask me a payment- or product-related question to get started, for example: "
        "‘Can I pay with PayPal?’ or ‘What is your return policy?’",
        "Hi there! I’m your device support assistant. "
        "Ask me a device-related question to get started, for example: "
        "‘How do I perform a soft reset on my device?’",
    ):
        assert message in script

    create_start = script.index("async function createSession()")
    create_end = script.index("\n}\n", create_start)
    create_block = script[create_start:create_end]
    assert "showTenantPlaceholder();" in create_block


def test_ui_projects_verified_tenant_and_user_scope_onto_sessions(
    client: TestClient,
) -> None:
    html = client.get("/").text
    script = client.get("/static/app.js").text
    styles = client.get("/static/styles.css").text

    assert 'class="identity-lock tenant-lock"' in html
    assert 'class="identity-lock user-lock"' in html
    assert "Tenant scope" in html
    assert "User scope" in html
    assert "Session isolation" in html
    assert 'id="active-session-scope"' in html
    assert 'scopeBadge.className = "scope-envelope session-scope";' in script
    assert "no other user or tenant can read this" in script
    assert 'badge: `${identity.tenant_id} · ${shortUser}`' in script
    assert ".scope-envelope::before" in styles
    assert ".identity-lock.user-lock" in styles


def test_ui_scrubs_previous_identity_state_before_login_or_logout(client: TestClient) -> None:
    script = client.get("/static/app.js").text
    reset_start = script.index("function resetWorkspaceState()")
    reset_end = script.index("\n}\n", reset_start)
    reset_block = script[reset_start:reset_end]
    for statement in (
        "messages.replaceChildren();",
        "sessionsNode.replaceChildren();",
        'document.querySelector("#identity-name").textContent = "";',
        'document.querySelector("#identity-tenant").textContent = "";',
        'document.querySelector("#trace-request").textContent = "—";',
        'document.querySelector("#trace-tools").textContent = "None";',
        'document.querySelector("#trace-sources").textContent = "None";',
    ):
        assert statement in reset_block

    login_start = script.index('loginForm.addEventListener("submit"')
    login_end = script.index("\n});", login_start)
    login_block = script[login_start:login_end]
    assert login_block.index("resetWorkspaceState();") < login_block.index(
        "setIdentity(result.identity);"
    )

    logout_start = script.index('document.querySelector("#logout")')
    logout_end = script.index("\n});", logout_start)
    logout_block = script[logout_start:logout_end]
    assert logout_block.index("resetWorkspaceState();") < logout_block.index('api("/auth/logout"')
