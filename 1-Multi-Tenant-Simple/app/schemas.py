"""
Pydantic request/response schemas for the multi-tenant RAG chatbot API.

These schemas define the contract between the API and its consumers,
providing validation and serialization for all endpoints.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Tenant schemas
# ──────────────────────────────────────────────

class TenantResponse(BaseModel):
    """Single tenant in the API response."""
    tenant_id: str
    tenant_name: str
    created_at: str
    metadata: Optional[dict[str, Any]] = None


class TenantListResponse(BaseModel):
    """Response for GET /api/tenants."""
    tenants: list[TenantResponse]


# ──────────────────────────────────────────────
# Auth schemas
# ──────────────────────────────────────────────

class TokenResponse(BaseModel):
    """Response for POST /api/auth/token."""
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    role: str


# ──────────────────────────────────────────────
# Chat schemas
# ──────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""
    # tenant_id is now derived from the JWT token — this field is ignored by the
    # backend but kept as optional for backward compatibility with older clients.
    tenant_id: Optional[str] = Field(None, description="Ignored; tenant is determined by the JWT token")
    session_id: Optional[str] = Field(None, description="Existing session ID, or null to create a new one")
    message: str = Field(..., min_length=1, max_length=4000, description="The user's question")


class SourceInfo(BaseModel):
    """A single source citation from RAG retrieval."""
    source_id: str
    tenant_id: str
    source_path: str
    heading: Optional[str] = None
    chunk_index: int
    excerpt: str


class ChatResponse(BaseModel):
    """Response body for POST /api/chat."""
    tenant_id: str
    session_id: str
    answer: str
    sources: list[SourceInfo] = []


class StreamSetupEvent(BaseModel):
    """Setup event data for the SSE stream."""
    session_id: str
    sources: list[SourceInfo] = []


class StreamDoneEvent(BaseModel):
    """Done event data for the SSE stream."""
    latency_ms: int


class ChatErrorResponse(BaseModel):
    """Error response body."""
    detail: str


# ──────────────────────────────────────────────
# Session schemas
# ──────────────────────────────────────────────

class SessionResponse(BaseModel):
    """Single session metadata."""
    session_id: str
    tenant_id: str
    title: Optional[str] = None
    created_at: str
    updated_at: str


class SessionListResponse(BaseModel):
    """Response for GET /api/sessions."""
    sessions: list[SessionResponse]


class SessionDeleteResponse(BaseModel):
    """Response for DELETE /api/sessions/{session_id}."""
    session_id: str
    status: str = "deleted"


class MessageResponse(BaseModel):
    """A single chat message."""
    role: str
    content: str


class SessionDetailResponse(BaseModel):
    """Response for GET /api/sessions/{session_id}."""
    session_id: str
    tenant_id: str
    title: Optional[str] = None
    created_at: str
    updated_at: str
    messages: list[MessageResponse] = []


# ──────────────────────────────────────────────
# Admin schemas
# ──────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Response for GET /api/health."""
    status: str
    sqlite: str
    tenant_count: int
    indexed_tenants: list[str]
    chat_model: str
    embedding_model: str
    chroma_mode: str


class ReindexRequest(BaseModel):
    """Request body for POST /api/admin/reindex."""
    tenant_id: Optional[str] = None


class ReindexTenantResult(BaseModel):
    """Reindex result for a single tenant."""
    tenant_id: str
    documents: int
    chunks: int


class ReindexResponse(BaseModel):
    """Response for POST /api/admin/reindex."""
    status: str
    reindexed: list[ReindexTenantResult]
