"""Embedded Redis-compatible order store with signed prefix enforcement."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol

import fakeredis.aioredis

from app.auth.tokens import RSATokenAuthority
from app.shared.capability_tokens import verify_store_credential
from app.shared.claims import AuthorizationError

ORDER_RECORDS = {
    "tenant-A": [
        {
            "order_id": "A-1001",
            "status": "paid",
            "amount": "89.00",
            "currency": "GBP",
            "updated_at": "2026-01-08T10:30:00Z",
        },
        {
            "order_id": "A-1002",
            "status": "refund_pending",
            "amount": "32.50",
            "currency": "GBP",
            "updated_at": "2026-01-12T09:15:00Z",
        },
        {
            "order_id": "A-1003",
            "status": "refunded",
            "amount": "120.00",
            "currency": "GBP",
            "updated_at": "2026-01-14T16:45:00Z",
        },
    ],
    "tenant-B": [
        {
            "order_id": "B-2001",
            "status": "payment_failed",
            "amount": "249.00",
            "currency": "GBP",
            "updated_at": "2026-02-02T11:00:00Z",
        },
        {
            "order_id": "B-2002",
            "status": "returned",
            "amount": "79.95",
            "currency": "GBP",
            "updated_at": "2026-02-06T13:20:00Z",
        },
        {
            "order_id": "B-2003",
            "status": "paid",
            "amount": "59.00",
            "currency": "GBP",
            "updated_at": "2026-02-09T08:10:00Z",
        },
    ],
}


class OrderStore(Protocol):
    """Boundary implemented by embedded and future native Redis adapters."""

    async def seed(self) -> None: ...

    async def query(
        self,
        *,
        credential: str,
        order_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    async def get_exact(self, *, credential: str, key: str) -> dict[str, Any] | None: ...


class EmbeddedOrderStore:
    """A fakeredis-backed adapter that verifies scope before every datastore read."""

    def __init__(self, authority: RSATokenAuthority) -> None:
        self.authority = authority
        self.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def seed(self) -> None:
        """Idempotently seed tenant-prefixed records and a JSON index."""

        for tenant_id, records in ORDER_RECORDS.items():
            prefix = f"tenant:{tenant_id}:orders:"
            ids = [record["order_id"] for record in records]
            await self.redis.set(f"{prefix}index", json.dumps(ids))
            for record in records:
                await self.redis.set(f"{prefix}{record['order_id']}", json.dumps(record))

    def _authorize(self, credential: str, *, operation: str, key: str) -> dict[str, Any]:
        claims = verify_store_credential(self.authority, credential)
        if operation not in claims["operations"]:
            raise AuthorizationError("Order-store operation is not permitted")
        if not key.startswith(claims["prefix"]):
            raise AuthorizationError("Order-store key is outside the credential scope")
        return claims

    async def _get(self, credential: str, key: str) -> str | None:
        self._authorize(credential, operation="get", key=key)
        value = await self.redis.get(key)
        if isinstance(value, bytes):
            return value.decode()
        return value

    async def _mget(self, credential: str, keys: Sequence[str]) -> list[str | None]:
        for key in keys:
            self._authorize(credential, operation="mget", key=key)
        if not keys:
            return []
        values = await self.redis.mget(list(keys))
        return [value.decode() if isinstance(value, bytes) else value for value in values]

    async def query(
        self,
        *,
        credential: str,
        order_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return only records within the signed tenant prefix."""

        claims = verify_store_credential(self.authority, credential)
        prefix = claims["prefix"]
        if order_id:
            record = await self.get_exact(credential=credential, key=f"{prefix}{order_id}")
            records = [record] if record else []
        else:
            index_raw = await self._get(credential, f"{prefix}index")
            ids = json.loads(index_raw) if index_raw else []
            raw_records = await self._mget(credential, [f"{prefix}{item}" for item in ids])
            records = [json.loads(raw) for raw in raw_records if raw]
        if status:
            records = [record for record in records if record.get("status") == status]
        return records[:limit]

    async def get_exact(self, *, credential: str, key: str) -> dict[str, Any] | None:
        """Read one exact key only after a signed prefix check."""

        raw = await self._get(credential, key)
        return json.loads(raw) if raw else None

    async def close(self) -> None:
        """Release the embedded client."""

        await self.redis.aclose()
