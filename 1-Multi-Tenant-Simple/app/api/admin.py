"""
Admin API routes.

Provides health check and reindex endpoints for operational use.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_admin
from app.config import settings
from app.db import check_db_health
from app.rag.vector_store import get_indexed_tenants, index_all_tenants, index_tenant
from app.schemas import (
    HealthResponse,
    MessageResponse,
    ReindexRequest,
    ReindexResponse,
    ReindexTenantResult,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
)
from app.services.chat import get_session, list_sessions, load_recent_messages
from app.services.tenants import get_tenant_count, list_tenants
from app.services.tenants import validate_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Check application health status.

    Returns app status, SQLite connectivity, tenant count,
    indexed tenants, and configured model names (without secrets).
    """
    sqlite_status = await check_db_health()
    tenant_count = await get_tenant_count()
    indexed = get_indexed_tenants()

    return HealthResponse(
        status="ok" if sqlite_status == "ok" else "degraded",
        sqlite=sqlite_status,
        tenant_count=tenant_count,
        indexed_tenants=indexed,
        chat_model=settings.chat_model,
        embedding_model=settings.embedding_model,
        chroma_mode=settings.chroma_mode,
    )


@router.get(
    "/admin/tenants/{tenant_id}/sessions",
    response_model=SessionListResponse,
    dependencies=[Depends(require_admin)],
)
async def get_admin_tenant_sessions(tenant_id: str) -> SessionListResponse:
    """List one tenant's sessions for the read-only administrator workspace."""
    await validate_tenant(tenant_id)
    sessions = await list_sessions(tenant_id)

    return SessionListResponse(
        sessions=[
            SessionResponse(
                session_id=session.session_id,
                tenant_id=session.tenant_id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
            )
            for session in sessions
        ]
    )


@router.get(
    "/admin/tenants/{tenant_id}/sessions/{session_id}",
    response_model=SessionDetailResponse,
    dependencies=[Depends(require_admin)],
)
async def get_admin_tenant_session_detail(
    tenant_id: str,
    session_id: str,
) -> SessionDetailResponse:
    """Open one tenant-owned session in the read-only administrator workspace."""
    await validate_tenant(tenant_id)
    session = await get_session(session_id)
    if session is None or session.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = load_recent_messages(session_id, max_messages=100)
    return SessionDetailResponse(
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            MessageResponse(role=message["role"], content=message["content"])
            for message in messages
        ],
    )


@router.post("/admin/reindex", response_model=ReindexResponse, dependencies=[Depends(require_admin)])
async def reindex(request: ReindexRequest):
    """
    Rebuild the in-memory vector index.

    Requires admin role JWT. Reindexes a single tenant if tenant_id is
    provided, otherwise reindexes all registered tenants.
    """
    try:
        if request.tenant_id:
            # Reindex a single tenant
            result = await index_tenant(request.tenant_id)
            results = [result]
        else:
            # Reindex all tenants
            tenants = await list_tenants()
            tenant_ids = [t.tenant_id for t in tenants]
            results = await index_all_tenants(tenant_ids)

        return ReindexResponse(
            status="ok",
            reindexed=[
                ReindexTenantResult(
                    tenant_id=r["tenant_id"],
                    documents=r["documents"],
                    chunks=r["chunks"],
                )
                for r in results
            ],
        )

    except Exception as e:
        logger.error("Reindex failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Reindex failed: {str(e)}",
        )
