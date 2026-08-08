"""SQLite schema, idempotent migrations, and deterministic demo seeds."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.auth.passwords import hash_password

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY,
    tenant_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    display_metadata_json TEXT NULL
);
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);
CREATE TABLE IF NOT EXISTS browser_sessions (
    browser_session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    user_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata_json TEXT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
);
CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    service TEXT NOT NULL,
    tenant_id TEXT NULL,
    user_id TEXT NULL,
    session_id TEXT NULL,
    action TEXT NOT NULL,
    target TEXT NULL,
    decision TEXT NOT NULL,
    status_code INTEGER NULL,
    latency_ms INTEGER NULL,
    details_json TEXT NULL
);
CREATE TABLE IF NOT EXISTS properties (
    property_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, property_id),
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_scope
ON chat_sessions (tenant_id, user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_scope
ON chat_messages (tenant_id, user_id, session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events (request_id);
CREATE INDEX IF NOT EXISTS idx_properties_scope ON properties (tenant_id, city, status);
"""

TENANTS = (
    ("tenant-A", "Tenant A Demo Store", "active", '{"accent":"cobalt"}'),
    ("tenant-B", "Tenant B Device Support", "active", '{"accent":"amber"}'),
)

USERS = (
    ("user-tenant-a-alice", "alice@tenant-a.demo", "tenant-A", "alice-demo"),
    ("user-tenant-a-carol", "carol@tenant-a.demo", "tenant-A", "carol-demo"),
    ("user-tenant-b-bob", "bob@tenant-b.demo", "tenant-B", "bob-demo"),
    ("user-tenant-b-jake", "jake@tenant-b.demo", "tenant-B", "jake-demo"),
)

PROPERTIES = (
    ("PA-101", "tenant-A", "Harbour Ledger House", "Bristol", "active"),
    ("PA-102", "tenant-A", "Copper Quay Depot", "Liverpool", "maintenance"),
    ("PA-103", "tenant-A", "Juniper Court", "Leeds", "inactive"),
    ("PB-201", "tenant-B", "Signal Workshop", "Manchester", "active"),
    ("PB-202", "tenant-B", "Firmware House", "Cambridge", "maintenance"),
    ("PB-203", "tenant-B", "Blue Light Annex", "Glasgow", "active"),
)


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(UTC).isoformat()


class SQLiteStore:
    """Connection factory and bootstrap operations for project-local SQLite state."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        """Open a foreign-key-aware row connection with a bounded busy timeout."""

        connection = sqlite3.connect(self.path, timeout=3, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 3000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit a unit of work or roll it back on failure."""

        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        """Apply the idempotent local schema."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)

    def seed(self) -> None:
        """Insert demo tenants, hashed users, and properties without duplication."""

        now = utc_now()
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO tenants
                    (tenant_id, tenant_name, status, created_at, display_metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                ((*tenant, now, metadata) for *tenant, metadata in TENANTS),
            )
            for user_id, username, tenant_id, password in USERS:
                exists = connection.execute(
                    "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()
                if exists is None:
                    connection.execute(
                        """
                        INSERT INTO users
                            (user_id, username, tenant_id, password_hash, status, created_at)
                        VALUES (?, ?, ?, ?, 'active', ?)
                        """,
                        (user_id, username, tenant_id, hash_password(password), now),
                    )
            connection.executemany(
                """
                INSERT OR IGNORE INTO properties
                    (property_id, tenant_id, name, city, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ((*record, now) for record in PROPERTIES),
            )

    def tenant(self, tenant_id: str) -> dict[str, Any] | None:
        """Return an active tenant registry row."""

        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM tenants WHERE tenant_id = ? AND status = 'active'", (tenant_id,)
            ).fetchone()
        return dict(row) if row else None

    def health(self) -> bool:
        """Verify schema reachability."""

        try:
            with closing(self.connect()) as connection:
                row = connection.execute("SELECT 1").fetchone()
                return bool(row is not None and int(row[0]) == 1)
        except sqlite3.Error:
            return False
