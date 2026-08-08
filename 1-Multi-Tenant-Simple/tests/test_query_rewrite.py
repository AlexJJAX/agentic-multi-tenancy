"""Contextual retrieval rewriting must remain useful and tenant-secret-free."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.config import settings
from app.rag.chain import rewrite_retrieval_query


@pytest.mark.asyncio
async def test_follow_up_is_rewritten_without_tenant_identity_in_prompt() -> None:
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content="approved duplicate payment refund processing time"
    )
    history = [
        {"role": "human", "content": "I was charged twice."},
        {"role": "ai", "content": "A settled duplicate can be refunded."},
    ]
    with patch.object(settings, "query_rewrite_enabled", True):
        rewritten = await rewrite_retrieval_query(
            tenant_id="tenant-A",
            session_id="session-1",
            user_message="How long does it take?",
            chat_history=history,
            model=model,
        )

    assert rewritten == "approved duplicate payment refund processing time"
    prompt_messages = model.ainvoke.await_args.args[0]
    assert "tenant-A" not in str(prompt_messages)
    assert "I was charged twice" in str(prompt_messages)
    assert model.ainvoke.await_args.kwargs["config"]["metadata"]["tenant_id"] == "tenant-A"


@pytest.mark.asyncio
async def test_disabled_rewrite_keeps_raw_query_without_model_call() -> None:
    model = AsyncMock()
    with patch.object(settings, "query_rewrite_enabled", False):
        rewritten = await rewrite_retrieval_query(
            tenant_id="tenant-A",
            session_id="session-1",
            user_message="How long does it take?",
            chat_history=[{"role": "human", "content": "A duplicate charge"}],
            model=model,
        )

    assert rewritten == "How long does it take?"
    model.ainvoke.assert_not_awaited()
