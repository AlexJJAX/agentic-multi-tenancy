"""Minimal structured audit repository."""

from __future__ import annotations

import json
from contextlib import closing
from typing import Any
from uuid import uuid4

from app.shared.redaction import redact
from app.stores.sqlite import SQLiteStore, utc_now


class AuditRepository:
    """Write correlation-friendly events without prompts, responses, or credentials."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def record(
        self,
        *,
        request_id: str,
        service: str,
        action: str,
        decision: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        target: str | None = None,
        status_code: int | None = None,
        latency_ms: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Persist one redacted event."""

        safe_details = redact(details or {})
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_events
                    (audit_id, request_id, occurred_at, service, tenant_id, user_id,
                     session_id, action, target, decision, status_code, latency_ms, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    request_id,
                    utc_now(),
                    service,
                    tenant_id,
                    user_id,
                    session_id,
                    action,
                    target,
                    decision,
                    status_code,
                    latency_ms,
                    json.dumps(safe_details, separators=(",", ":")),
                ),
            )

    def for_request(self, request_id: str) -> list[dict[str, Any]]:
        """Return events for tests and local diagnostics."""

        with closing(self.store.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE request_id = ? ORDER BY occurred_at",
                (request_id,),
            ).fetchall()
        return [dict(row) for row in rows]
