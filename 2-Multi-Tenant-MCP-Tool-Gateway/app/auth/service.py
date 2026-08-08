"""Local identity service with separate user and service credential flows."""

from __future__ import annotations

import hmac
from contextlib import closing
from typing import Any

from app.auth.passwords import verify_password
from app.auth.tokens import RSATokenAuthority
from app.settings import Settings
from app.shared.claims import AuthenticationError, AuthorizationError, normalize_tenant_claim
from app.shared.models import Principal
from app.shared.runtime_secrets import RuntimeSecrets
from app.stores.sqlite import SQLiteStore

SERVICE_GRANTS = {
    "mcp-gateway-service": {
        "properties-mcp": "mcp.tools.call",
        "orders-target": "tools.invoke",
    },
    "orders-target-service": {"local-tvm": "credentials.issue"},
}


class IdentityService:
    """Authenticate seeded users and mint narrowly audience-bound credentials."""

    def __init__(
        self,
        *,
        store: SQLiteStore,
        authority: RSATokenAuthority,
        settings: Settings,
        secrets: RuntimeSecrets,
    ) -> None:
        self.store = store
        self.authority = authority
        self.settings = settings
        self.secrets = secrets

    def authenticate_user(self, username: str, password: str) -> Principal:
        """Verify a seeded password and return a signed platform principal."""

        with closing(self.store.connect()) as connection:
            row = connection.execute(
                """
                SELECT u.*, t.status AS tenant_status
                FROM users AS u
                JOIN tenants AS t ON t.tenant_id = u.tenant_id
                WHERE lower(u.username) = lower(?)
                """,
                (username,),
            ).fetchone()
        if (
            row is None
            or row["status"] != "active"
            or row["tenant_status"] != "active"
            or not verify_password(password, row["password_hash"])
        ):
            raise AuthenticationError("Invalid username or password")
        token = self.authority.issue(
            subject=row["user_id"],
            audience=["chat-agent", "mcp-gateway", "properties-mcp-user-context"],
            ttl_seconds=self.settings.user_token_ttl_seconds,
            claims={
                "preferred_username": row["username"],
                "tenant_id": row["tenant_id"],
                "custom:tenant_id": row["tenant_id"],
                "azp": "chat-ui",
            },
        )
        return Principal(
            user_id=row["user_id"],
            username=row["username"],
            tenant_id=row["tenant_id"],
            token=token,
        )

    def validate_user_token(self, token: str, *, audience: str) -> Principal:
        """Validate a user token and active tenant membership for one audience."""

        claims = self.authority.decode(token, audience=audience, azp="chat-ui")
        tenant_id = normalize_tenant_claim(claims)
        if self.store.tenant(tenant_id) is None:
            raise AuthorizationError("Unknown or inactive tenant")
        username = claims.get("preferred_username")
        subject = claims.get("sub")
        if (
            not isinstance(username, str)
            or not username.strip()
            or not isinstance(subject, str)
            or not subject.strip()
        ):
            raise AuthenticationError("User identity claims are incomplete")
        return Principal(
            user_id=subject,
            username=username,
            tenant_id=tenant_id,
            token=token,
        )

    def issue_service_token(self, *, client_id: str, client_secret: str, audience: str) -> str:
        """Authenticate one local service client and mint only its registered audience."""

        expected_secret = {
            self.settings.gateway_service_client_id: self.secrets.gateway_service_client_secret,
            self.settings.orders_service_client_id: self.secrets.orders_service_client_secret,
        }.get(client_id)
        grant = SERVICE_GRANTS.get(client_id, {}).get(audience)
        if (
            expected_secret is None
            or grant is None
            or not hmac.compare_digest(client_secret, expected_secret)
        ):
            raise AuthenticationError("Invalid service client credentials")
        return self.authority.issue(
            subject=f"service-account-{client_id}",
            audience=audience,
            ttl_seconds=self.settings.service_token_ttl_seconds,
            claims={"azp": client_id, "scope": grant},
        )

    def validate_service_token(
        self,
        token: str,
        *,
        audience: str,
        client_id: str,
        scope: str,
    ) -> dict[str, Any]:
        """Validate the independent service credential intended for a target."""

        return self.authority.decode(
            token,
            audience=audience,
            azp=client_id,
            required_scope=scope,
        )
