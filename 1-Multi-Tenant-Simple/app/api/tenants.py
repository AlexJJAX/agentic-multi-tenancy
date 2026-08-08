"""
Tenant API routes.

Provides endpoints for listing and retrieving tenant information.
"""

from fastapi import APIRouter

from app.schemas import TenantListResponse, TenantResponse
from app.services.tenants import get_tenant, list_tenants

router = APIRouter(prefix="/api", tags=["tenants"])


@router.get("/tenants", response_model=TenantListResponse)
async def get_tenants():
    """
    List all registered tenants.

    Returns tenant IDs, display names, and metadata for populating
    the UI tenant selector.
    """
    tenants = await list_tenants()
    return TenantListResponse(tenants=tenants)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant_by_id(tenant_id: str):
    """
    Get a single tenant by ID.

    Returns 404 if the tenant does not exist.
    """
    return await get_tenant(tenant_id)
