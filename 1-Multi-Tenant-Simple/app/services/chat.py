"""
Chat session and message service.

Handles chat session creation, message persistence using
LangChain's SQLChatMessageHistory, and session retrieval.
"""

import logging
import uuid
from datetime import datetime, timezone

from langchain_community.chat_message_histories import SQLChatMessageHistory
from sqlalchemy import select

from app.config import settings
from app.db import get_db_session
from app.models import ChatSession

logger = logging.getLogger(__name__)


async def create_session(tenant_id: str, title: str | None = None) -> str:
    """
    Create a new chat session for a tenant.

    Args:
        tenant_id: The tenant this session belongs to.
        title: Optional session title.

    Returns:
        The newly created session ID.
    """
    session_id = f"session_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    async with get_db_session() as db:
        chat_session = ChatSession(
            session_id=session_id,
            tenant_id=tenant_id,
            title=title or f"Chat session {session_id[:16]}",
            created_at=now,
            updated_at=now,
        )
        db.add(chat_session)

    logger.info("Created session %s for tenant %s", session_id, tenant_id)
    return session_id


async def get_session(session_id: str) -> ChatSession | None:
    """
    Get a chat session by ID.

    Args:
        session_id: The session to look up.

    Returns:
        ChatSession object or None.
    """
    async with get_db_session() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.session_id == session_id)
        )
        return result.scalar_one_or_none()


async def list_sessions(tenant_id: str) -> list[ChatSession]:
    """
    List all chat sessions for a tenant.

    Args:
        tenant_id: The tenant whose sessions to list.

    Returns:
        List of ChatSession objects.
    """
    async with get_db_session() as db:
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.tenant_id == tenant_id)
            .order_by(ChatSession.updated_at.desc())
        )
        return list(result.scalars().all())


async def delete_session(session_id: str, tenant_id: str) -> bool:
    """Delete a tenant-owned chat session and all of its stored messages.

    The ownership check is part of the database query so a tenant cannot
    delete another tenant's session by guessing its identifier.

    Args:
        session_id: The session to delete.
        tenant_id: The authenticated tenant that must own the session.

    Returns:
        True when the session was deleted, otherwise False.
    """
    async with get_db_session() as db:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.session_id == session_id,
                ChatSession.tenant_id == tenant_id,
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            return False

        # SQLChatMessageHistory owns its message table, so use its public
        # clear operation after the tenant ownership check succeeds.
        get_chat_history(session_id).clear()
        await db.delete(session)

    logger.info("Deleted session %s for tenant %s", session_id, tenant_id)
    return True


async def update_session_timestamp(session_id: str) -> None:
    """
    Update the session's updated_at timestamp.

    Args:
        session_id: The session to update.
    """
    async with get_db_session() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.session_id == session_id)
        )
        session = result.scalar_one_or_none()
        if session:
            session.updated_at = datetime.now(timezone.utc).isoformat()


def get_chat_history(session_id: str) -> SQLChatMessageHistory:
    """
    Get a LangChain SQL chat history instance for a session.

    Uses the synchronous SQLite URL since SQLChatMessageHistory
    does not support async.

    Args:
        session_id: The session ID to use as the history key.

    Returns:
        SQLChatMessageHistory instance.
    """
    return SQLChatMessageHistory(
        session_id=session_id,
        connection=settings.sqlite_sync_url,
    )


def load_recent_messages(
    session_id: str,
    max_messages: int | None = None,
) -> list[dict]:
    """
    Load recent chat messages for a session.

    Args:
        session_id: The session to load history for.
        max_messages: Maximum number of messages to return.

    Returns:
        List of message dicts with "role" and "content" keys.
    """
    if max_messages is None:
        max_messages = settings.chat_history_max_messages

    history = get_chat_history(session_id)
    messages = history.messages

    # Take the most recent messages within the window
    recent = messages[-max_messages:] if len(messages) > max_messages else messages

    return [
        {"role": msg.type, "content": msg.content}
        for msg in recent
    ]


def save_messages(
    session_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    """
    Save a user/assistant message pair to the chat history.

    Args:
        session_id: The session to save messages for.
        user_message: The user's question.
        assistant_message: The assistant's answer.
    """
    history = get_chat_history(session_id)
    history.add_user_message(user_message)
    history.add_ai_message(assistant_message)
    logger.info("Saved messages to session %s", session_id)
