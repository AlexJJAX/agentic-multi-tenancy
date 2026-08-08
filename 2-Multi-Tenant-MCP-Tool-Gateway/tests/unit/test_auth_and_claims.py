"""Identity claim, password, key cache, and audience tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.auth.jwks import ensure_rsa_keypair
from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import JWKSCache, RSATokenAuthority, verify_user_with_jwks
from app.shared.claims import AuthenticationError, AuthorizationError, normalize_tenant_claim


def test_scrypt_hash_is_salted_and_verifiable() -> None:
    first = hash_password("demo-password")
    second = hash_password("demo-password")
    assert first != second
    assert "demo-password" not in first
    assert verify_password("demo-password", first)
    assert not verify_password("wrong", first)


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"tenant_id": "tenant-A"}, "tenant-A"),
        ({"custom:tenant_id": "tenant-B"}, "tenant-B"),
        (
            {"tenant_id": "tenant-A", "custom:tenant_id": "tenant-A"},
            "tenant-A",
        ),
    ],
)
def test_tenant_claim_normalization(claims: dict[str, str], expected: str) -> None:
    assert normalize_tenant_claim(claims) == expected


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"tenant_id": ""},
        {"tenant_id": "../../tenant-A"},
        {"tenant_id": "tenant-A", "custom:tenant_id": "tenant-B"},
    ],
)
def test_tenant_claim_normalization_fails_closed(claims: dict[str, str]) -> None:
    with pytest.raises(AuthorizationError):
        normalize_tenant_claim(claims)


def test_user_and_service_audiences_are_not_substitutable(runtime) -> None:  # type: ignore[no-untyped-def]
    principal = runtime.identity.authenticate_user("alice@tenant-a.demo", "alice-demo")
    with pytest.raises(AuthenticationError):
        runtime.identity.validate_service_token(
            principal.token,
            audience="properties-mcp",
            client_id=runtime.settings.gateway_service_client_id,
            scope="mcp.tools.call",
        )
    service_token = runtime.identity.issue_service_token(
        client_id=runtime.settings.gateway_service_client_id,
        client_secret=runtime.secrets.gateway_service_client_secret,
        audience="properties-mcp",
    )
    with pytest.raises(AuthenticationError):
        runtime.identity.validate_user_token(service_token, audience="chat-agent")


def _authority(root: Path, name: str) -> RSATokenAuthority:
    private = root / f"{name}-private.pem"
    public = root / f"{name}-public.pem"
    ensure_rsa_keypair(private, public, generate=True)
    return RSATokenAuthority(private, public, "https://issuer.test")


def test_unknown_kid_causes_one_controlled_refresh(tmp_path: Path) -> None:
    first = _authority(tmp_path, "first")
    second = _authority(tmp_path, "second")
    current = {"authority": first, "fetches": 0}

    def fetch() -> dict[str, object]:
        current["fetches"] += 1
        return current["authority"].jwks()

    cache = JWKSCache(fetch)
    token_one = first.issue(
        subject="user-1",
        audience="mcp-gateway",
        ttl_seconds=60,
        claims={
            "azp": "chat-ui",
            "preferred_username": "one@example.test",
            "tenant_id": "tenant-A",
        },
    )
    verify_user_with_jwks(
        token_one,
        cache=cache,
        issuer="https://issuer.test",
        audience="mcp-gateway",
    )
    assert current["fetches"] == 1
    current["authority"] = second
    token_two = second.issue(
        subject="user-2",
        audience="mcp-gateway",
        ttl_seconds=60,
        claims={
            "azp": "chat-ui",
            "preferred_username": "two@example.test",
            "tenant_id": "tenant-B",
        },
    )
    verify_user_with_jwks(
        token_two,
        cache=cache,
        issuer="https://issuer.test",
        audience="mcp-gateway",
    )
    assert current["fetches"] == 2
