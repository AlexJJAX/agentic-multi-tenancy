"""
RAG chain orchestration module.

Implements the full RAG flow: history retrieval, query building,
vector search, tenant validation, prompt construction, LLM invocation,
and source formatting.
"""

import logging
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import settings
from app.rag.citations import format_context_for_prompt, format_sources
from app.rag.prompts import ANSWER_PROMPT_TEMPLATE, SYSTEM_PROMPT_TEMPLATE
from app.rag.vector_store import retrieve_for_tenant
from app.schemas import SourceInfo
from app.services.tracing import trace_config

logger = logging.getLogger(__name__)


def get_chat_model() -> ChatOpenAI:
    """
    Get a configured ChatOpenAI instance.

    Uses gpt-5-mini by default, configurable via CHAT_MODEL env var.

    Returns:
        Configured ChatOpenAI instance.
    """
    return ChatOpenAI(
        model=settings.chat_model,
        openai_api_key=settings.require_openai_api_key(),
        temperature=0.1,  # Low temperature for grounded answers
    )


def build_retrieval_query(
    user_message: str,
    chat_history: list[dict],
) -> str:
    """
    Build a retrieval query from the user message and recent chat history.

    Combines the current question with recent context to handle
    follow-up questions that use pronouns or references.

    Args:
        user_message: The current user question.
        chat_history: Recent chat messages as list of {"role": str, "content": str}.

    Returns:
        Enhanced retrieval query string.
    """
    # Kept as the deterministic baseline used by the ablation notebook.
    return user_message


def _text_content(content: Any) -> str:
    """Normalize text-only and block-style model response content."""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


async def rewrite_retrieval_query(
    *,
    tenant_id: str,
    session_id: str,
    user_message: str,
    chat_history: list[dict],
    model: BaseChatModel | None = None,
) -> str:
    """Rewrite a follow-up into a standalone search query with one model call.

    The rewriter receives conversational text only. Tenant identity remains trace
    metadata and is never placed in the prompt. Failure falls back to the raw
    question so retrieval remains available during tracing/model outages.
    """

    baseline = build_retrieval_query(user_message, chat_history)
    if not settings.query_rewrite_enabled or not chat_history:
        return baseline

    recent_history = format_chat_history(chat_history[-4:])
    selected_model = model or ChatOpenAI(
        model=settings.query_rewrite_model,
        openai_api_key=settings.require_openai_api_key(),
        temperature=0,
    )
    try:
        response = await selected_model.ainvoke(
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite the current question as one concise, standalone search query. "
                        "Resolve pronouns from the conversation. Preserve product IDs, policy "
                        "terms, and user intent. Return only the query."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Recent conversation:\n{recent_history}\n\n"
                        f"Current question:\n{user_message}"
                    ),
                },
            ],
            config=trace_config(
                tenant_id=tenant_id,
                session_id=session_id,
                stage="query-rewrite",
            ),
        )
        rewritten = _text_content(response.content).strip().strip('"')
        if rewritten:
            logger.info("Rewrote a contextual retrieval query for tenant %s", tenant_id)
            return rewritten
    except Exception:
        logger.warning("Query rewriting failed; using raw question", exc_info=True)
    return baseline


def format_chat_history(messages: list[dict]) -> str:
    """
    Format chat history messages into a string for the prompt.

    Args:
        messages: List of message dicts with "role" and "content".

    Returns:
        Formatted chat history string.
    """
    if not messages:
        return "(No previous messages in this session.)"

    parts = []
    for msg in messages:
        role = "User" if msg["role"] == "human" else "Assistant"
        parts.append(f"{role}: {msg['content']}")

    return "\n".join(parts)


async def run_rag_chain(
    tenant_id: str,
    tenant_name: str,
    session_id: str,
    user_message: str,
    chat_history: list[dict],
) -> tuple[str, list[SourceInfo], int]:
    """
    Execute the full RAG chain for a chat request.

    Steps:
    1. Build retrieval query from user message + chat history
    2. Retrieve relevant chunks from tenant's Chroma collection
    3. Validate all chunks belong to the correct tenant
    4. Build grounded prompt with context and history
    5. Invoke the chat model
    6. Format source citations

    Args:
        tenant_id: The tenant to answer for.
        tenant_name: The tenant display name.
        session_id: The current chat session ID.
        user_message: The user's question.
        chat_history: Recent chat messages for context.

    Returns:
        Tuple of (answer text, source list, latency in ms).

    Raises:
        RuntimeError: If cross-tenant retrieval is detected.
    """
    start_time = time.time()

    # Step 1: Build retrieval query
    retrieval_query = await rewrite_retrieval_query(
        tenant_id=tenant_id,
        session_id=session_id,
        user_message=user_message,
        chat_history=chat_history,
    )
    logger.info("Retrieval query built for tenant %s", tenant_id)

    # Step 2 & 3: Retrieve and validate chunks (validation happens inside)
    retrieved_docs = retrieve_for_tenant(tenant_id, retrieval_query)

    # Step 4: Build the prompt
    context_str = format_context_for_prompt(retrieved_docs)
    history_str = format_chat_history(chat_history)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        tenant_id=tenant_id,
        tenant_name=tenant_name,
    )

    answer_prompt = ANSWER_PROMPT_TEMPLATE.format(
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        context=context_str,
        chat_history=history_str,
        user_message=user_message,
    )

    # Step 5: Invoke the chat model
    model = get_chat_model()
    response = await model.ainvoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": answer_prompt},
        ],
        config=trace_config(
            tenant_id=tenant_id,
            session_id=session_id,
            stage="grounded-answer",
        ),
    )
    answer = _text_content(response.content)
    latency_ms = int((time.time() - start_time) * 1000)

    # Step 6: Format source citations
    sources = format_sources(retrieved_docs, tenant_id)

    logger.info(
        "RAG chain complete for tenant %s, session %s: "
        "%d sources, %dms latency",
        tenant_id,
        session_id,
        len(sources),
        latency_ms,
    )

    return answer, sources, latency_ms


async def stream_rag_chain(
    tenant_id: str,
    tenant_name: str,
    session_id: str,
    user_message: str,
    chat_history: list[dict],
):
    """
    Execute the RAG chain and stream the response.
    
    Yields:
        tuples of (event_type: str, data: Any)
        - ("setup", {"sources": list[SourceInfo]})
        - ("token", str)
        - ("done", dict)
    """
    start_time = time.time()

    # Step 1: Build retrieval query
    retrieval_query = await rewrite_retrieval_query(
        tenant_id=tenant_id,
        session_id=session_id,
        user_message=user_message,
        chat_history=chat_history,
    )
    logger.info("Retrieval query built for tenant %s", tenant_id)

    # Step 2 & 3: Retrieve and validate chunks
    retrieved_docs = retrieve_for_tenant(tenant_id, retrieval_query)
    
    # Format sources immediately so we can yield them
    sources = format_sources(retrieved_docs, tenant_id)
    yield ("setup", {"sources": sources})

    # Step 4: Build the prompt
    context_str = format_context_for_prompt(retrieved_docs)
    history_str = format_chat_history(chat_history)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        tenant_id=tenant_id,
        tenant_name=tenant_name,
    )

    answer_prompt = ANSWER_PROMPT_TEMPLATE.format(
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        context=context_str,
        chat_history=history_str,
        user_message=user_message,
    )

    # Step 5: Stream the chat model
    full_answer = []
    model = get_chat_model()
    async for chunk in model.astream(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": answer_prompt},
        ],
        config=trace_config(
            tenant_id=tenant_id,
            session_id=session_id,
            stage="grounded-answer",
        ),
    ):
        token = _text_content(chunk.content)
        if token:
            full_answer.append(token)
            yield ("token", token)

    latency_ms = int((time.time() - start_time) * 1000)

    answer = "".join(full_answer)
    logger.info(
        "RAG streaming complete for tenant %s, session %s: "
        "%d sources, %dms latency",
        tenant_id,
        session_id,
        len(sources),
        latency_ms,
    )

    yield (
        "done",
        {"latency_ms": latency_ms, "answer": answer},
    )
