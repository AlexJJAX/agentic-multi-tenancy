"""
FastAPI dependencies for JWT-based authentication.

Provides reusable Depends(...) callables that extract and validate
JWTs from the Authorization header, returning structured principal objects.
"""

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.services.auth import decode_access_token

logger = logging.getLogger(__name__)

# OAuth2PasswordBearer reads the token from the Authorization: Bearer <token> header.
# tokenUrl points to the login endpoint so FastAPI's /docs UI can populate it.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def get_current_tenant_id(token: str = Depends(oauth2_scheme)) -> str:
    """
    FastAPI dependency: extract and validate the tenant_id from the JWT.

    Usage::

        @router.post("/chat")
        async def send_message(tenant_id: str = Depends(get_current_tenant_id)):
            ...

    Returns:
        The tenant_id claim from the validated JWT.

    Raises:
        HTTP 401: If the token is missing, invalid, or expired.
    """
    payload = decode_access_token(token)
    tenant_id: str = payload.get("tenant_id", "")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing the tenant_id claim.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return tenant_id


def get_current_user_role(token: str = Depends(oauth2_scheme)) -> str:
    """
    FastAPI dependency: extract the role claim from the JWT.

    Returns:
        The role claim string (e.g., "user" or "admin").
    """
    payload = decode_access_token(token)
    return payload.get("role", "user")


def require_admin(role: str = Depends(get_current_user_role)) -> None:
    """
    FastAPI dependency: require the caller to have the admin role.

    Raises:
        HTTP 403: If the user's role is not "admin".
    """
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for this operation.",
        )
