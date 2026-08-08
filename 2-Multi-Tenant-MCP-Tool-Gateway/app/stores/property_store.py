"""SQLite row-level-security emulator for tenant-scoped property reads."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Protocol

from app.shared.claims import AuthorizationError
from app.stores.sqlite import SQLiteStore


class PropertyStore(Protocol):
    """Boundary implemented by SQLite and future native PostgreSQL adapters."""

    def query(
        self,
        *,
        tenant_id: str,
        property_id: str | None,
        city: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...


def install_property_authorizer(connection: sqlite3.Connection) -> None:
    """Deny protected-table reads unless SQLite attributes them to the approved view."""

    def authorize(
        action: int,
        arg1: str | None,
        _arg2: str | None,
        _database: str | None,
        source: str | None,
    ) -> int:
        if (
            action == sqlite3.SQLITE_READ
            and arg1 == "properties"
            and source != "visible_properties"
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)


class SQLitePropertyStore:
    """Fresh-connection tenant context, protected view, and authorizer enforcement."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def scoped_connection(self, tenant_id: str) -> sqlite3.Connection:
        """Create one request-local context and protected view, then lock direct reads."""

        if self.store.tenant(tenant_id) is None:
            raise AuthorizationError("Unknown or inactive tenant")
        connection = self.store.connect()
        try:
            connection.execute("CREATE TEMP TABLE current_tenant (tenant_id TEXT NOT NULL)")
            connection.execute("INSERT INTO current_tenant (tenant_id) VALUES (?)", (tenant_id,))
            connection.execute(
                """
                CREATE TEMP VIEW visible_properties AS
                SELECT p.*
                FROM main.properties AS p
                JOIN temp.current_tenant AS t ON p.tenant_id = t.tenant_id
                """
            )
            install_property_authorizer(connection)
            return connection
        except Exception:
            connection.close()
            raise

    def query(
        self,
        *,
        tenant_id: str,
        property_id: str | None,
        city: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Query only the tenant-filtered view on a disposable connection."""

        connection = self.scoped_connection(tenant_id)
        try:
            rows = connection.execute(
                """
                SELECT property_id, name, city, status, created_at
                FROM visible_properties
                WHERE (? IS NULL OR property_id = ?)
                  AND (? IS NULL OR lower(city) = lower(?))
                  AND (? IS NULL OR status = ?)
                ORDER BY property_id
                LIMIT ?
                """,
                (property_id, property_id, city, city, status, status, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def direct_read_denied(self, tenant_id: str) -> bool:
        """Diagnostic used by tests to prove the base table cannot be read."""

        connection = self.scoped_connection(tenant_id)
        try:
            connection.execute("SELECT * FROM properties").fetchall()
        except sqlite3.DatabaseError:
            return True
        finally:
            connection.close()
        return False

    def new_connection_has_tenant_context(self) -> bool:
        """Prove tenant state is not present on a fresh connection."""

        with closing(self.store.connect()) as connection:
            row = connection.execute(
                "SELECT 1 FROM sqlite_temp_master WHERE name = 'current_tenant'"
            ).fetchone()
        return row is not None
