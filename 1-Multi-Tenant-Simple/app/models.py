"""
SQLAlchemy ORM models for the multi-tenant RAG chatbot.

Defines the database schema for tenants, chat sessions,
tenant documents, and RAG telemetry events.
"""

from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


class Tenant(Base):
    """
    Tenant registry table.

    Stores tenant identifiers, display names, and optional metadata.
    Each tenant has isolated knowledge base content and chat sessions.
    """
    __tablename__ = "tenants"

    tenant_id = Column(Text, primary_key=True)
    tenant_name = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)

    # Relationships
    sessions = relationship("ChatSession", back_populates="tenant", lazy="selectin")
    documents = relationship("TenantDocument", back_populates="tenant", lazy="selectin")


class ChatSession(Base):
    """
    Chat session table.

    Groups chat messages into conversations, scoped to a specific tenant.
    """
    __tablename__ = "chat_sessions"

    session_id = Column(Text, primary_key=True)
    tenant_id = Column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    title = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="sessions")


class TenantDocument(Base):
    """
    Tenant document tracking table.

    Records which markdown files have been ingested and indexed
    for each tenant, along with content hashes for change detection.
    """
    __tablename__ = "tenant_documents"

    document_id = Column(Text, primary_key=True)
    tenant_id = Column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    source_path = Column(Text, nullable=False)
    content_hash = Column(Text, nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    indexed_at = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="pending")

    # Relationships
    tenant = relationship("Tenant", back_populates="documents")


class RagEvent(Base):
    """
    RAG telemetry events table.

    Records each chat request with retrieval metadata for local
    debugging and observability. Never logs API keys.
    """
    __tablename__ = "rag_events"

    event_id = Column(Text, primary_key=True)
    tenant_id = Column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    session_id = Column(Text, nullable=True)
    user_message = Column(Text, nullable=False)
    retrieved_chunk_ids_json = Column(Text, nullable=True)
    chat_model = Column(Text, nullable=False)
    embedding_model = Column(Text, nullable=False)
    latency_ms = Column(Integer, nullable=True)
    status = Column(Text, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)
