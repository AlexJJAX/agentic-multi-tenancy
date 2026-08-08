"""
Chat API routes.

Provides endpoints for sending chat messages and managing sessions.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_tenant_id
from app.schemas import (
    ChatErrorResponse,
    ChatRequest,
    ChatResponse,
    MessageResponse,
    SessionDeleteResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
)
from app.services.chat import (
    create_session,
    delete_session,
    get_session,
    list_sessions,
    load_recent_messages,
    save_messages,
    update_session_timestamp,
)
from app.services.telemetry import log_rag_event
from app.services.tenants import validate_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: {"model": ChatErrorResponse},
        401: {"model": ChatErrorResponse},
        404: {"model": ChatErrorResponse},
        500: {"model": ChatErrorResponse},
    },
)
async def send_chat_message(
    request: ChatRequest,
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Send a chat message and receive a RAG-generated answer.

    Requires a valid Bearer token in the Authorization header.
    The tenant_id is derived exclusively from the JWT — the optional
    tenant_id body field is ignored.

    Validates the tenant, creates a session if needed, retrieves
    relevant context from the tenant's knowledge base, and generates
    a grounded answer using gpt-5-mini.
    """
    # Step 1: Validate tenant exists (uses JWT-derived tenant_id)
    tenant = await validate_tenant(tenant_id)

    # Step 2: Validate message is non-empty (Pydantic handles min_length)
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Step 3: Create session if needed
    session_id = request.session_id
    if not session_id:
        session_id = await create_session(tenant_id)

    # Verify session exists and belongs to the correct tenant
    if request.session_id:
        existing_session = await get_session(session_id)
        if existing_session is None:
            # Session doesn't exist, create a new one
            session_id = await create_session(tenant_id)
        elif existing_session.tenant_id != tenant_id:
            raise HTTPException(
                status_code=400,
                detail="Session does not belong to the specified tenant",
            )

    try:
        # Step 4: Load recent chat history
        chat_history = load_recent_messages(session_id)

        async def sse_generator():
            try:
                # Import here to avoid circular imports if any, or use from top
                from app.rag.chain import stream_rag_chain
                from app.schemas import StreamSetupEvent, StreamDoneEvent
                import json

                # Step 5: Stream the RAG chain
                stream = stream_rag_chain(
                    tenant_id=tenant_id,
                    tenant_name=tenant.tenant_name,
                    session_id=session_id,
                    user_message=request.message,
                    chat_history=chat_history,
                )

                final_answer = ""
                final_sources = []
                final_latency = 0

                async for event_type, data in stream:
                    if event_type == "setup":
                        final_sources = data["sources"]
                        setup_event = StreamSetupEvent(
                            session_id=session_id,
                            sources=final_sources,
                        )
                        yield f"event: setup\ndata: {setup_event.model_dump_json()}\n\n"
                    elif event_type == "token":
                        yield f"event: token\ndata: {json.dumps(data)}\n\n"
                    elif event_type == "done":
                        final_latency = data["latency_ms"]
                        final_answer = data["answer"]
                        done_event = StreamDoneEvent(
                            latency_ms=final_latency,
                        )
                        yield f"event: done\ndata: {done_event.model_dump_json()}\n\n"

                # Step 6: Save messages to chat history
                save_messages(session_id, request.message, final_answer)

                # Step 7: Update session timestamp
                await update_session_timestamp(session_id)

                # Step 8: Log RAG event
                retrieved_chunk_ids = [s.source_id for s in final_sources]
                await log_rag_event(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    user_message=request.message,
                    retrieved_chunk_ids=retrieved_chunk_ids,
                    latency_ms=final_latency,
                    status="ok",
                )
            except RuntimeError as e:
                # Cross-tenant isolation error
                logger.critical("Isolation error: %s", e)
                await log_rag_event(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    user_message=request.message,
                    retrieved_chunk_ids=None,
                    latency_ms=None,
                    status="isolation_error",
                    error_message=str(e),
                )
                yield f"event: error\ndata: {json.dumps('An internal isolation error occurred. Please contact support.')}\n\n"
            except Exception as e:
                logger.error("Chat error for tenant %s: %s", tenant_id, e)
                await log_rag_event(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    user_message=request.message,
                    retrieved_chunk_ids=None,
                    latency_ms=None,
                    status="error",
                    error_message=str(e),
                )
                yield f"event: error\ndata: {json.dumps('An unexpected error occurred during streaming.')}\n\n"

        from fastapi.responses import StreamingResponse
        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    except Exception as e:
        logger.error("Error setting up chat for tenant %s: %s", tenant_id, e)
        error_msg = "Failed to generate a response. "
        if "api_key" in str(e).lower() or "authentication" in str(e).lower():
            error_msg += "Please check that OPENAI_API_KEY is set correctly."
        else:
            error_msg += "Please try again later."
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/sessions", response_model=SessionListResponse)
async def get_sessions(tenant_id: str = Depends(get_current_tenant_id)):
    """
    List all chat sessions for the authenticated tenant.

    The tenant is derived from the JWT token — no query parameter needed.
    """
    # Validate tenant exists
    await validate_tenant(tenant_id)

    sessions = await list_sessions(tenant_id)
    return SessionListResponse(
        sessions=[
            SessionResponse(
                session_id=s.session_id,
                tenant_id=s.tenant_id,
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ]
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionDeleteResponse,
    responses={
        401: {"model": ChatErrorResponse},
        404: {"model": ChatErrorResponse},
    },
)
async def delete_saved_session(
    session_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
):
    """Delete a saved session owned by the authenticated tenant."""
    deleted = await delete_session(session_id, tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionDeleteResponse(session_id=session_id)


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session_detail(
    session_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
):
    """
    Get session details including chat messages.

    Returns session metadata and all messages for debugging/display.
    """
    session = await get_session(session_id)
    if session is None or session.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Session not found")

    # Load all messages for this session
    messages = load_recent_messages(session_id, max_messages=100)

    return SessionDetailResponse(
        session_id=session.session_id,
        tenant_id=session.tenant_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            MessageResponse(role=m["role"], content=m["content"])
            for m in messages
        ],
    )
