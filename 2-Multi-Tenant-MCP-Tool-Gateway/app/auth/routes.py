"""Identity, browser login, JWKS, and session routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.shared.claims import AuthenticationError, AuthorizationError
from app.shared.models import BrowserIdentity, Principal

if TYPE_CHECKING:
    from app.lifespan import AppRuntime

router = APIRouter()
SESSION_COOKIE = "mt_session"


class LoginRequest(BaseModel):
    """Seeded demo login input."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    """Browser-safe login result."""

    identity: BrowserIdentity


def _runtime(request: Request) -> AppRuntime:
    return cast("AppRuntime", request.app.state.runtime)


def require_browser_principal(
    request: Request,
    browser_session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Principal:
    """Resolve an opaque browser cookie to a freshly validated user principal."""

    if not browser_session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    runtime = _runtime(request)
    stored = runtime.browser_sessions.get(browser_session_id)
    if stored is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    try:
        principal = runtime.identity.validate_user_token(
            stored["user_token"], audience="chat-agent"
        )
    except (AuthenticationError, AuthorizationError) as exc:
        runtime.browser_sessions.delete(browser_session_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    if principal.user_id != stored["user_id"] or principal.tenant_id != stored["tenant_id"]:
        runtime.browser_sessions.delete(browser_session_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session binding invalid",
        )
    return principal


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, request: Request) -> LoginResponse:
    """Authenticate a demo account and set an opaque HttpOnly session cookie."""

    runtime = _runtime(request)
    try:
        principal = runtime.identity.authenticate_user(payload.username, payload.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    browser_session_id = runtime.browser_sessions.create(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        user_token=principal.token,
    )
    response.set_cookie(
        SESSION_COOKIE,
        browser_session_id,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=runtime.settings.session_ttl_seconds,
        path="/",
    )
    tenant = runtime.store.tenant(principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive tenant")
    return LoginResponse(
        identity=BrowserIdentity(
            user_id=principal.user_id,
            username=principal.username,
            tenant_id=principal.tenant_id,
            tenant_name=tenant["tenant_name"],
        )
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    browser_session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    """Invalidate the current browser session and clear its cookie."""

    if browser_session_id:
        _runtime(request).browser_sessions.delete(browser_session_id)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/api/me", response_model=BrowserIdentity)
def me(
    request: Request,
    principal: Annotated[Principal, Depends(require_browser_principal)],
) -> BrowserIdentity:
    """Return verified identity information without a tenant-switching control."""

    tenant = _runtime(request).store.tenant(principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive tenant")
    return BrowserIdentity(
        user_id=principal.user_id,
        username=principal.username,
        tenant_id=principal.tenant_id,
        tenant_name=tenant["tenant_name"],
    )


@router.post("/auth/token")
def service_token(
    request: Request,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    client_secret: Annotated[str, Form()],
    audience: Annotated[str, Form()],
) -> dict[str, str | int]:
    """Issue a local client-credentials-style service token."""

    if grant_type != "client_credentials":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported grant type",
        )
    runtime = _runtime(request)
    try:
        token = runtime.identity.issue_service_token(
            client_id=client_id,
            client_secret=client_secret,
            audience=audience,
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": runtime.settings.service_token_ttl_seconds,
    }


@router.get("/.well-known/openid-configuration")
def issuer_metadata(request: Request) -> dict[str, str | list[str]]:
    """Publish the minimal local issuer metadata used by this demo."""

    issuer = _runtime(request).settings.identity_issuer
    return {
        "issuer": issuer,
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "token_endpoint": f"{issuer}/auth/token",
        "grant_types_supported": ["client_credentials"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    }


@router.get("/.well-known/jwks.json")
def jwks(request: Request) -> dict[str, Any]:
    """Expose only the identity authority's public signing key."""

    return _runtime(request).identity.authority.jwks()
