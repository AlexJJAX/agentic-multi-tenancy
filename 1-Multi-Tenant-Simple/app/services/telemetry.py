"""
Local telemetry service for RAG events.

Records each chat request with retrieval metadata for debugging
and observability. Never logs API keys.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from app.db import get_db_session
from app.models import RagEvent
from app.config import settings

logger = logging.getLogger(__name__)


async def log_rag_event(
    tenant_id: str,
    session_id: str | None,
    user_message: str,
    retrieved_chunk_ids: list[str] | None,
    latency_ms: int | None,
    status: str,
    error_message: str | None = None,
) -> None:
    """
    Record a RAG event to the rag_events table.

    This provides local observability into the RAG pipeline
    for debugging and demo purposes.

    Args:
        tenant_id: The tenant this event belongs to.
        session_id: The chat session ID (may be None).
        user_message: The user's question.
        retrieved_chunk_ids: List of chunk IDs that were retrieved.
        latency_ms: Total latency in milliseconds.
        status: Event status ("ok", "error", "isolation_error").
        error_message: Error description if status is not "ok".
    """
    event_id = f"evt_{uuid.uuid4().hex[:12]}"

    try:
        async with get_db_session() as db:
            event = RagEvent(
                event_id=event_id,
                tenant_id=tenant_id,
                session_id=session_id,
                user_message=user_message,
                retrieved_chunk_ids_json=(
                    json.dumps(retrieved_chunk_ids) if retrieved_chunk_ids else None
                ),
                chat_model=settings.chat_model,
                embedding_model=settings.embedding_model,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            db.add(event)

        logger.info(
            "RAG event logged: tenant=%s, session=%s, status=%s, latency=%sms",
            tenant_id,
            session_id,
            status,
            latency_ms,
        )
    except Exception as e:
        # Telemetry should never crash the main flow
        logger.error("Failed to log RAG event: %s", e)
