"""Target-specific service token cache with verified expiry."""

from __future__ import annotations

import time

from app.auth.service import IdentityService


class ServiceTokenCache:
    """Cache service credentials by audience without mixing user authorization context."""

    def __init__(self, identity: IdentityService) -> None:
        self.identity = identity
        self._cache: dict[tuple[str, str], tuple[str, int]] = {}

    def get(
        self,
        *,
        client_id: str,
        client_secret: str,
        audience: str,
        scope: str,
    ) -> str:
        """Return a verified token, refreshing it before its expiry window."""

        cache_key = (client_id, audience)
        cached = self._cache.get(cache_key)
        if cached and cached[1] - 15 > int(time.time()):
            return cached[0]
        token = self.identity.issue_service_token(
            client_id=client_id,
            client_secret=client_secret,
            audience=audience,
        )
        claims = self.identity.validate_service_token(
            token,
            audience=audience,
            client_id=client_id,
            scope=scope,
        )
        self._cache[cache_key] = (token, int(claims["exp"]))
        return token

    def clear(self) -> None:
        """Discard application-owned cached credentials on shutdown."""

        self._cache.clear()
