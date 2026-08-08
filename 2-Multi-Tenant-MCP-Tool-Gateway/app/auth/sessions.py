"""Server-side browser session persistence."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from app.stores.sqlite import SQLiteStore, utc_now


class BrowserSessionRepository:
    """Persist opaque, tenant-bound browser sessions without exposing JWTs to JavaScript."""

    def __init__(self, store: SQLiteStore, ttl_seconds: int) -> None:
        self.store = store
        self.ttl_seconds = ttl_seconds

    def create(self, *, user_id: str, tenant_id: str, user_token: str) -> str:
        """Rotate to a new random identifier and persist its server-side token context."""

        session_id = secrets.token_urlsafe(32)
        expires_at = (datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)).isoformat()
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM browser_sessions WHERE user_id = ?", (user_id,))
            connection.execute(
                """
                INSERT INTO browser_sessions
                    (browser_session_id, user_id, tenant_id, user_token, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, user_id, tenant_id, user_token, utc_now(), expires_at),
            )
        return session_id

    def get(self, browser_session_id: str) -> dict[str, str] | None:
        """Load a non-expired session and remove stale state fail-closed."""

        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM browser_sessions WHERE browser_session_id = ?",
                (browser_session_id,),
            ).fetchone()
            if row is None:
                return None
            if datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
                connection.execute(
                    "DELETE FROM browser_sessions WHERE browser_session_id = ?",
                    (browser_session_id,),
                )
                return None
            return {key: str(row[key]) for key in row.keys()}

    def delete(self, browser_session_id: str) -> None:
        """Invalidate a browser session immediately."""

        with self.store.transaction() as connection:
            connection.execute(
                "DELETE FROM browser_sessions WHERE browser_session_id = ?",
                (browser_session_id,),
            )
