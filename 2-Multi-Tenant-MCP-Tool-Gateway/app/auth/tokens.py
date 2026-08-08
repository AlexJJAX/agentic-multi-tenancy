"""Audience-bound RSA JWT issuance and independent verification."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
from jwt import PyJWTError

from app.auth.jwks import key_id, public_jwk
from app.shared.claims import AuthenticationError, AuthorizationError, normalize_tenant_claim

JWKSFetcher = Callable[[], dict[str, Any]]


class JWKSCache:
    """Small JWKS cache that refreshes exactly once for an unknown ``kid``."""

    def __init__(self, fetcher: JWKSFetcher) -> None:
        self._fetcher = fetcher
        self._keys: dict[str, Any] = {}

    def refresh(self) -> None:
        """Replace cached keys with the provider's current signing set."""

        payload = self._fetcher()
        self._keys = {
            item["kid"]: jwt.PyJWK.from_dict(item).key
            for item in payload.get("keys", [])
            if isinstance(item, dict) and isinstance(item.get("kid"), str)
        }

    def signing_key(self, token: str) -> Any:
        """Resolve the token's key, refreshing once when rotation introduces a new ``kid``."""

        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except PyJWTError as exc:
            raise AuthenticationError("Malformed token header") from exc
        if not isinstance(kid, str):
            raise AuthenticationError("Missing token key identifier")
        key = self._keys.get(kid)
        if key is None:
            self.refresh()
            key = self._keys.get(kid)
        if key is None:
            raise AuthenticationError("Unknown token signing key")
        return key


class RSATokenAuthority:
    """Issue and validate one family of purpose-bound RS256 tokens."""

    def __init__(self, private_path: Path, public_path: Path, issuer: str) -> None:
        self.private_pem = private_path.read_bytes()
        self.public_pem = public_path.read_bytes()
        self.issuer = issuer
        self.kid = key_id(self.public_pem)

    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        """Return the public JSON Web Key Set."""

        return {"keys": [public_jwk(self.public_pem)]}

    def issue(
        self,
        *,
        subject: str,
        audience: str | list[str],
        ttl_seconds: int,
        claims: dict[str, Any],
    ) -> str:
        """Issue a short-lived token with mandatory temporal and unique claims."""

        now = int(time.time())
        payload = {
            "iss": self.issuer,
            "sub": subject,
            "aud": [audience] if isinstance(audience, str) else audience,
            "iat": now,
            "nbf": now,
            "exp": now + ttl_seconds,
            "jti": str(uuid4()),
            **claims,
        }
        return jwt.encode(payload, self.private_pem, algorithm="RS256", headers={"kid": self.kid})

    def decode(
        self,
        token: str,
        *,
        audience: str,
        azp: str | None = None,
        required_scope: str | None = None,
    ) -> dict[str, Any]:
        """Verify signature, issuer, times, audience, subject, party, and optional scope."""

        try:
            claims = jwt.decode(
                token,
                self.public_pem,
                algorithms=["RS256"],
                audience=audience,
                issuer=self.issuer,
                options={"require": ["iss", "sub", "aud", "iat", "nbf", "exp", "jti"]},
            )
        except PyJWTError as exc:
            raise AuthenticationError("Invalid or expired token") from exc
        if azp is not None and claims.get("azp") != azp:
            raise AuthenticationError("Token authorized party is invalid")
        if required_scope is not None:
            scopes = str(claims.get("scope", "")).split()
            if required_scope not in scopes:
                raise AuthorizationError("Token scope is insufficient")
        return claims


def verify_user_with_jwks(
    token: str,
    *,
    cache: JWKSCache,
    issuer: str,
    audience: str,
    azp: str = "chat-ui",
) -> dict[str, Any]:
    """Independently verify a user token against a refreshable JWKS cache."""

    key = cache.signing_key(token)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["iss", "sub", "aud", "iat", "nbf", "exp", "jti"]},
        )
    except PyJWTError as exc:
        raise AuthenticationError("Invalid or expired user token") from exc
    if claims.get("azp") != azp:
        raise AuthenticationError("User token authorized party is invalid")
    if not isinstance(claims.get("sub"), str) or not claims["sub"].strip():
        raise AuthenticationError("User token subject is invalid")
    if (
        not isinstance(claims.get("preferred_username"), str)
        or not claims["preferred_username"].strip()
    ):
        raise AuthenticationError("User token username is invalid")
    normalize_tenant_claim(claims)
    return claims
