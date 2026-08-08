"""Fail-closed chat session and message persistence."""

from __future__ import annotations

import json
from contextlib import closing
from typing import Any
from uuid import UUID, uuid4

from app.shared.claims import AuthorizationError
from app.stores.sqlite import SQLiteStore, utc_now


class HistoryRepository:
    """Require tenant, user, and session scope for every history operation."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def create_session(self, *, tenant_id: str, user_id: str, title: str | None = None) -> str:
        """Create an unguessable chat session bound to one tenant and user."""

        session_id = str(uuid4())
        now = utc_now()
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO chat_sessions
                    (session_id, tenant_id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, tenant_id, user_id, title, now, now),
            )
        return session_id

    def require_session(self, *, tenant_id: str, user_id: str, session_id: str) -> dict[str, Any]:
        """Reject malformed, unknown, or foreign sessions without revealing ownership."""

        try:
            UUID(session_id)
        except ValueError as exc:
            raise AuthorizationError("Chat session is unavailable") from exc
        with closing(self.store.connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM chat_sessions
                WHERE session_id = ? AND tenant_id = ? AND user_id = ?
                """,
                (session_id, tenant_id, user_id),
            ).fetchone()
        if row is None:
            raise AuthorizationError("Chat session is unavailable")
        return dict(row)

    def list_sessions(self, *, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        """List only sessions within the caller's immutable scope."""

        with closing(self.store.connect()) as connection:
            rows = connection.execute(
                """
                SELECT session_id, title, created_at, updated_at
                FROM chat_sessions
                WHERE tenant_id = ? AND user_id = ?
                ORDER BY updated_at DESC
                """,
                (tenant_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_session(self, *, tenant_id: str, user_id: str, session_id: str) -> bool:
        """Delete one owned session and its messages in a scoped transaction."""

        try:
            UUID(session_id)
        except ValueError:
            return False
        with self.store.transaction() as connection:
            owned = connection.execute(
                """
                SELECT 1 FROM chat_sessions
                WHERE session_id = ? AND tenant_id = ? AND user_id = ?
                """,
                (session_id, tenant_id, user_id),
            ).fetchone()
            if owned is None:
                return False
            connection.execute(
                """
                DELETE FROM chat_messages
                WHERE session_id = ? AND tenant_id = ? AND user_id = ?
                """,
                (session_id, tenant_id, user_id),
            )
            deleted = connection.execute(
                """
                DELETE FROM chat_sessions
                WHERE session_id = ? AND tenant_id = ? AND user_id = ?
                """,
                (session_id, tenant_id, user_id),
            )
        return deleted.rowcount == 1

    def messages(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Load chronological messages after verifying all three scope components."""

        self.require_session(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
        query = """
            SELECT message_id, role, content, metadata_json, created_at
            FROM chat_messages
            WHERE session_id = ? AND tenant_id = ? AND user_id = ?
            ORDER BY created_at DESC
        """
        values: list[Any] = [session_id, tenant_id, user_id]
        if limit is not None:
            query += " LIMIT ?"
            values.append(limit)
        with closing(self.store.connect()) as connection:
            rows = connection.execute(query, values).fetchall()
        return [dict(row) for row in reversed(rows)]

    def append_exchange(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str,
        user_message: str,
        assistant_message: str,
        assistant_metadata: dict[str, Any],
    ) -> tuple[str, str]:
        """Atomically persist one successful user/assistant exchange."""

        self.require_session(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
        now = utc_now()
        user_message_id = str(uuid4())
        assistant_message_id = str(uuid4())
        with self.store.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO chat_messages
                    (message_id, session_id, tenant_id, user_id, role, content,
                     metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        user_message_id,
                        session_id,
                        tenant_id,
                        user_id,
                        "user",
                        user_message,
                        None,
                        now,
                    ),
                    (
                        assistant_message_id,
                        session_id,
                        tenant_id,
                        user_id,
                        "assistant",
                        assistant_message,
                        json.dumps(assistant_metadata, separators=(",", ":")),
                        now,
                    ),
                ),
            )
            connection.execute(
                """
                UPDATE chat_sessions
                SET updated_at = ?, title = COALESCE(title, ?)
                WHERE session_id = ? AND tenant_id = ? AND user_id = ?
                """,
                (now, user_message[:60], session_id, tenant_id, user_id),
            )
        return user_message_id, assistant_message_id
