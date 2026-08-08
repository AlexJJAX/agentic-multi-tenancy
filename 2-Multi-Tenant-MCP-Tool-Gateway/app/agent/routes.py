"""Authenticated chat and session HTTP APIs."""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agent.formatting import strip_inline_source_references
from app.auth.routes import require_browser_principal
from app.shared.claims import AuthorizationError
from app.shared.models import Principal

if TYPE_CHECKING:
    from app.lifespan import AppRuntime

router = APIRouter(prefix="/api")


def _runtime(request: Request) -> AppRuntime:
    return cast("AppRuntime", request.app.state.runtime)


class CreateSessionRequest(BaseModel):
    """Optional session title input."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=120)


class ChatRequest(BaseModel):
    """Authenticated chat input; tenant identity is deliberately absent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str
    message: str = Field(min_length=1, max_length=4000)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(
    payload: CreateSessionRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_browser_principal)],
) -> dict[str, str | None]:
    """Create one tenant/user-bound conversation."""

    session_id = _runtime(request).history.create_session(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        title=payload.title,
    )
    return {"session_id": session_id, "title": payload.title}


@router.get("/sessions")
def list_sessions(
    request: Request,
    principal: Annotated[Principal, Depends(require_browser_principal)],
) -> list[dict[str, Any]]:
    """List only the caller's scoped sessions."""

    return _runtime(request).history.list_sessions(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )


@router.get("/sessions/{session_id}/messages")
def session_messages(
    session_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_browser_principal)],
) -> list[dict[str, Any]]:
    """Load messages only after tenant/user/session ownership verification."""

    try:
        messages = _runtime(request).history.messages(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            session_id=session_id,
        )
        for item in messages:
            if item["role"] == "assistant":
                item["content"] = strip_inline_source_references(item["content"])
        return messages
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_browser_principal)],
) -> Response:
    """Delete only a conversation owned by the authenticated tenant and user."""

    deleted = _runtime(request).history.delete_session(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        session_id=session_id,
    )
    _runtime(request).audit.record(
        request_id=request.state.request_id,
        service="chat-agent",
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        session_id=session_id,
        action="session-delete",
        target="chat-history",
        decision="allowed" if deleted else "denied",
        status_code=204 if deleted else 404,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session is unavailable",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_browser_principal)],
) -> dict[str, Any]:
    """Generate one grounded response using immutable authenticated tenant scope."""

    try:
        return await _runtime(request).chat.respond(
            principal=principal,
            session_id=payload.session_id,
            message=payload.message,
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        _runtime(request).audit.record(
            request_id="chat-error",
            service="chat-agent",
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            session_id=payload.session_id,
            action="chat",
            target="openai-or-tool",
            decision="error",
            status_code=502,
            details={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The assistant could not complete the request. Please retry.",
        ) from exc


def _sse(event: str, payload: Any) -> str:
    """Encode one server-sent event."""

    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("/chat/stream")
async def stream_chat(
    payload: ChatRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_browser_principal)],
) -> StreamingResponse:
    """Stream route progress, grounded answer text, sources, and trace metadata."""

    async def events():  # type: ignore[no-untyped-def]
        try:
            yield _sse("phase", {"node": "identity", "label": "Verified signed identity"})
            yield _sse("phase", {"node": "rag", "label": "Searched tenant collection"})
            result = await _runtime(request).chat.respond(
                principal=principal,
                session_id=payload.session_id,
                message=payload.message,
            )
            if result["trace"]["tools"]:
                yield _sse("phase", {"node": "gateway", "label": "Authorized MCP route"})
                yield _sse("phase", {"node": "target", "label": "Completed scoped store read"})
            for token in re.findall(r"\S+\s*", result["answer"]):
                yield _sse("token", token)
                await asyncio.sleep(0)
            yield _sse(
                "done",
                {
                    "session_id": result["session_id"],
                    "message_id": result["message_id"],
                    "sources": result["sources"],
                    "trace": result["trace"],
                },
            )
        except AuthorizationError:
            yield _sse("error", "The session is not visible to this account.")
        except Exception as exc:
            _runtime(request).audit.record(
                request_id="chat-stream-error",
                service="chat-agent",
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                session_id=payload.session_id,
                action="chat-stream",
                target="rag-and-mcp",
                decision="error",
                status_code=502,
                details={"error_type": type(exc).__name__},
            )
            yield _sse("error", "The assistant could not complete the request. Please retry.")

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
