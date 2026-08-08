"""
Tenant registry service.

Provides operations for listing, retrieving, and validating tenants
against the SQLite registry.
"""

import json
import logging

from fastapi import HTTPException
from sqlalchemy import func, select

from app.db import get_db_session
from app.models import Tenant
from app.schemas import TenantResponse

logger = logging.getLogger(__name__)


async def list_tenants() -> list[TenantResponse]:
    """
    List all registered tenants.

    Returns:
        List of tenant response objects with parsed metadata.
    """
    async with get_db_session() as session:
        result = await session.execute(select(Tenant).order_by(Tenant.tenant_id))
        tenants = result.scalars().all()

        return [
            TenantResponse(
                tenant_id=t.tenant_id,
                tenant_name=t.tenant_name,
                created_at=t.created_at,
                metadata=json.loads(t.metadata_json) if t.metadata_json else None,
            )
            for t in tenants
        ]


async def get_tenant(tenant_id: str) -> TenantResponse:
    """
    Get a single tenant by ID.

    Args:
        tenant_id: The tenant identifier to look up.

    Returns:
        Tenant response object.

    Raises:
        HTTPException: If the tenant is not found (404).
    """
    async with get_db_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.tenant_id == tenant_id)
        )
        tenant = result.scalar_one_or_none()

        if tenant is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown tenant: {tenant_id}",
            )

        return TenantResponse(
            tenant_id=tenant.tenant_id,
            tenant_name=tenant.tenant_name,
            created_at=tenant.created_at,
            metadata=json.loads(tenant.metadata_json) if tenant.metadata_json else None,
        )


async def validate_tenant(tenant_id: str) -> TenantResponse:
    """
    Validate that a tenant exists and return its data.

    This is the primary entry point for tenant validation before
    any chat or retrieval operation.

    Args:
        tenant_id: The tenant identifier to validate.

    Returns:
        Tenant response object if valid.

    Raises:
        HTTPException: If the tenant is not found (404).
    """
    return await get_tenant(tenant_id)


async def get_tenant_count() -> int:
    """Get the total number of registered tenants."""
    async with get_db_session() as session:
        result = await session.execute(select(func.count(Tenant.tenant_id)))
        return result.scalar_one()
