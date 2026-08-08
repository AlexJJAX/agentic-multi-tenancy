"""Protected HTTP adapter for the Lambda-style orders target."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from app.shared.claims import AuthenticationError, AuthorizationError, require_bearer

router = APIRouter(prefix="/internal/tools", include_in_schema=False)


class OrdersEnvelope(BaseModel):
    """Loose outer envelope; the service validates nested propagated context."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any]
    request_context: dict[str, Any]


@router.post("/orders")
async def invoke_orders(
    payload: OrdersEnvelope,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Invoke the target with mandatory gateway service authentication."""

    try:
        service_token = require_bearer(authorization)
        records = await request.app.state.runtime.orders_target.invoke(
            authorization=service_token,
            envelope=payload.model_dump(),
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {"records": records, "count": len(records)}
