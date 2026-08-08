"""LangChain agent with an injectable response backend for automated tests."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol, cast

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from app.agent.formatting import strip_inline_source_references
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.rag import RAGHit, TenantRAGService
from app.agent.tools import GatewayToolLoader
from app.audit.repository import AuditRepository
from app.gateway.routing import GatewayRouter
from app.history.repository import HistoryRepository
from app.settings import Settings
from app.shared.correlation import correlation_id
from app.shared.models import Principal

SIMPLE_GREETING_RESPONSE = "Hi — how can I help you today?"
SIMPLE_GREETING_PATTERN = re.compile(r"hi[,.!?]*", re.IGNORECASE)


def _rag_context(hits: list[RAGHit]) -> str:
    return (
        "\n\n".join(f"SOURCE [{hit.source} — {hit.section}]\n{hit.content}" for hit in hits)
        or "No relevant tenant document was retrieved."
    )


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part)
    return str(content)


def _is_simple_greeting(message: str) -> bool:
    """Recognize a standalone ``Hi`` without matching substantive requests."""

    return SIMPLE_GREETING_PATTERN.fullmatch(message.strip()) is not None


class ChatResponseBackend(Protocol):
    """Generate one response while leaving tenant enforcement in application code."""

    async def respond(
        self,
        *,
        principal: Principal,
        message: str,
        hits: list[RAGHit],
        history: list[dict[str, Any]],
        request_id: str,
        gateway_router: GatewayRouter,
    ) -> tuple[str, list[dict[str, Any]], list[str]]: ...


class OpenAIChatBackend:
    """Live OpenAI agent backend used by every normal application startup."""

    def __init__(self, *, settings: Settings, tool_loader: GatewayToolLoader) -> None:
        self.settings = settings
        self.tool_loader = tool_loader

    async def respond(
        self,
        *,
        principal: Principal,
        message: str,
        hits: list[RAGHit],
        history: list[dict[str, Any]],
        request_id: str,
        gateway_router: GatewayRouter,
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        """Load per-user MCP tools and let the configured OpenAI model answer."""

        del gateway_router
        tools = await self.tool_loader.load(user_token=principal.token, request_id=request_id)
        model = ChatOpenAI(
            model=self.settings.openai_chat_model,
            api_key=self.settings.openai_api_key,
            timeout=self.settings.openai_timeout_seconds,
        )
        agent = create_agent(
            model,
            tools,
            system_prompt=SYSTEM_PROMPT.format(rag_context=_rag_context(hits)),
        )
        messages: list[AnyMessage] = []
        for item in history:
            message_class = HumanMessage if item["role"] == "user" else AIMessage
            messages.append(message_class(content=item["content"]))
        messages.append(HumanMessage(content=message))
        config: RunnableConfig = {"recursion_limit": 12}
        result = await cast(Any, agent).ainvoke(
            {"messages": messages},
            config=config,
            version="v1",
        )
        response_messages = result.get("messages", [])
        answer = next(
            (
                _text_content(item.content)
                for item in reversed(response_messages)
                if isinstance(item, AIMessage) and _text_content(item.content)
            ),
            "The assistant did not produce a response.",
        )
        used_tools: list[str] = []
        tool_sources: list[dict[str, Any]] = []
        for item in response_messages:
            if not isinstance(item, ToolMessage):
                continue
            name = item.name or "unknown"
            used_tools.append(name)
            record_ids: list[str] = []
            try:
                payload = json.loads(_text_content(item.content))
                records = payload.get("records", []) if isinstance(payload, dict) else []
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    candidate = record.get("order_id") or record.get("property_id")
                    if isinstance(candidate, str):
                        record_ids.append(candidate)
            except json.JSONDecodeError:
                pass
            tool_sources.append(
                {"type": "tool", "name": name, "record_ids": [item for item in record_ids if item]}
            )
        return answer, tool_sources, list(dict.fromkeys(used_tools))


class ChatService:
    """Combine scoped history, tenant RAG, MCP tools, and final response generation."""

    def __init__(
        self,
        *,
        settings: Settings,
        rag: TenantRAGService,
        history: HistoryRepository,
        gateway_router: GatewayRouter,
        audit: AuditRepository,
        response_backend: ChatResponseBackend,
    ) -> None:
        self.settings = settings
        self.rag = rag
        self.history = history
        self.gateway_router = gateway_router
        self.audit = audit
        self.response_backend = response_backend

    async def respond(
        self,
        *,
        principal: Principal,
        session_id: str,
        message: str,
    ) -> dict[str, Any]:
        """Return one grounded answer and persist it only after successful completion."""

        request_id = correlation_id()
        history = self.history.messages(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            session_id=session_id,
            limit=self.settings.history_max_messages,
        )
        if not history and _is_simple_greeting(message):
            hits: list[RAGHit] = []
            answer = SIMPLE_GREETING_RESPONSE
            tool_sources: list[dict[str, Any]] = []
            tools: list[str] = []
        else:
            hits = self.rag.search(tenant_id=principal.tenant_id, query=message)
            answer, tool_sources, tools = await self.response_backend.respond(
                principal=principal,
                message=message,
                hits=hits,
                history=history,
                request_id=request_id,
                gateway_router=self.gateway_router,
            )
        answer = strip_inline_source_references(answer)
        document_sources = [
            {
                "type": "document",
                "source": hit.source,
                "section": hit.section,
                "chunk_index": hit.chunk_index,
                "excerpt": hit.content,
            }
            for hit in hits
        ]
        sources = [*tool_sources, *document_sources]
        _user_id, message_id = self.history.append_exchange(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            session_id=session_id,
            user_message=message,
            assistant_message=answer,
            assistant_metadata={"sources": sources, "request_id": request_id, "tools": tools},
        )
        self.audit.record(
            request_id=request_id,
            service="chat-agent",
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            session_id=session_id,
            action="chat",
            target="rag-and-mcp",
            decision="allowed",
            status_code=200,
            details={"tools": tools, "source_count": len(sources)},
        )
        return {
            "session_id": session_id,
            "message_id": message_id,
            "answer": answer,
            "sources": sources,
            "trace": {"request_id": request_id, "tools": tools},
        }
