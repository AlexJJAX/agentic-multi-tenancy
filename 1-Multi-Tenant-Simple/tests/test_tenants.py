"""
Tests for tenant seeding and registry operations.

Covers:
- T001: Tenant seeding creates tenant-A and tenant-B
- T005: Unknown tenant is rejected
"""

import pytest
import pytest_asyncio
from unittest.mock import patch

from app.models import Base
from app.seed import seed_tenants
from app.services.tenants import list_tenants, get_tenant, validate_tenant, get_tenant_count


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    """Create a fresh in-memory database for each test."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    test_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )

    # Create tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Patch the db module to use our test engine/session
    with patch("app.db.engine", test_engine), \
         patch("app.db.async_session_factory", test_session_factory), \
         patch("app.services.tenants.get_db_session") as mock_session:

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_get_db():
            async with test_session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        mock_session.side_effect = mock_get_db

        # Also patch the seed module's get_db_session
        with patch("app.seed.get_db_session", side_effect=mock_get_db):
            yield test_engine

    # Cleanup
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_seed_tenants_creates_both(setup_test_db):
    """T001: Tenant seeding creates tenant-A and tenant-B with non-empty names."""
    await seed_tenants()

    tenants = await list_tenants()
    tenant_ids = {t.tenant_id for t in tenants}

    assert "tenant-A" in tenant_ids, "tenant-A should be seeded"
    assert "tenant-B" in tenant_ids, "tenant-B should be seeded"

    # Verify non-empty names
    for t in tenants:
        assert t.tenant_name, f"Tenant {t.tenant_id} should have a non-empty name"


@pytest.mark.asyncio
async def test_seed_tenants_idempotent(setup_test_db):
    """Seeding twice should not create duplicates."""
    await seed_tenants()
    await seed_tenants()

    count = await get_tenant_count()
    assert count == 2, "Should still have exactly 2 tenants after double seed"


@pytest.mark.asyncio
async def test_get_tenant_exists(setup_test_db):
    """Get an existing tenant returns data."""
    await seed_tenants()

    tenant = await get_tenant("tenant-A")
    assert tenant.tenant_id == "tenant-A"
    assert "Acme" in tenant.tenant_name


@pytest.mark.asyncio
async def test_unknown_tenant_rejected(setup_test_db):
    """T005: Unknown tenant IDs are rejected with a clear error."""
    await seed_tenants()

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await validate_tenant("tenant-UNKNOWN")

    assert exc_info.value.status_code == 404
    assert "Unknown tenant" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_tenant_metadata_parsed(setup_test_db):
    """Tenant metadata is properly parsed from JSON."""
    await seed_tenants()

    tenant = await get_tenant("tenant-A")
    assert tenant.metadata is not None
    assert tenant.metadata.get("theme") == "blue"
    assert tenant.metadata.get("tier") == "demo"
