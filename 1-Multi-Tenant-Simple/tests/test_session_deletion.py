"""Regression tests for tenant-scoped saved-session deletion."""

from contextlib import asynccontextmanager
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base, ChatSession, Tenant
from app.services.chat import delete_session


@pytest.mark.asyncio
async def test_delete_session_removes_only_tenant_owned_session():
    """A tenant can delete its own metadata/history but not another tenant's."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add_all(
            [
                Tenant(
                    tenant_id="tenant-A",
                    tenant_name="Tenant A",
                    created_at="2026-07-26T08:00:00+00:00",
                ),
                Tenant(
                    tenant_id="tenant-B",
                    tenant_name="Tenant B",
                    created_at="2026-07-26T08:00:00+00:00",
                ),
                ChatSession(
                    session_id="session-a",
                    tenant_id="tenant-A",
                    title="Tenant A session",
                    created_at="2026-07-26T08:00:00+00:00",
                    updated_at="2026-07-26T08:00:00+00:00",
                ),
                ChatSession(
                    session_id="session-b",
                    tenant_id="tenant-B",
                    title="Tenant B session",
                    created_at="2026-07-26T08:00:00+00:00",
                    updated_at="2026-07-26T08:00:00+00:00",
                ),
            ]
        )
        await db.commit()

    @asynccontextmanager
    async def test_db_session():
        async with session_factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    tenant_a_history = Mock()
    with (
        patch("app.services.chat.get_db_session", side_effect=test_db_session),
        patch(
            "app.services.chat.get_chat_history",
            return_value=tenant_a_history,
        ) as mock_get_history,
    ):
        assert await delete_session("session-b", "tenant-A") is False
        mock_get_history.assert_not_called()

        assert await delete_session("session-a", "tenant-A") is True
        mock_get_history.assert_called_once_with("session-a")
        tenant_a_history.clear.assert_called_once_with()

    async with session_factory() as db:
        remaining = set(
            await db.scalars(select(ChatSession.session_id))
        )

    assert remaining == {"session-b"}
    await engine.dispose()
