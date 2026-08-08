"""Protected HTTP contract for the local TVM."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.shared.claims import AuthenticationError, AuthorizationError, require_bearer

router = APIRouter(prefix="/internal/tvm", include_in_schema=False)


@router.post("/v1/order-store-credentials")
def order_store_credentials(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    x_tenant_context: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> dict[str, object]:
    """Return a no-store credential whose tenant is derived only from its capability."""

    if not x_tenant_context or not x_request_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing TVM context")
    try:
        service_token = require_bearer(authorization)
        credential = request.app.state.runtime.tvm.issue_order_store_credential(
            service_token=service_token,
            capability=x_tenant_context,
            request_id=x_request_id,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    claims = request.app.state.runtime.gateway_authority.decode(credential, audience="order-store")
    response.headers["Cache-Control"] = "no-store"
    expires_at = datetime.fromtimestamp(claims["exp"], tz=UTC).isoformat()
    return {
        "credential": credential,
        "allowed_prefix": f"{claims['prefix']}*",
        "allowed_operations": claims["operations"],
        "expires_at": expires_at,
    }
