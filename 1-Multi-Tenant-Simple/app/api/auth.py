"""
Authentication API routes.

Provides the token endpoint for the OAuth2 Password Grant flow.
Clients POST username + password (form-encoded) and receive a
signed JWT access token in return.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.schemas import TokenResponse
from app.services.auth import authenticate_user, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post(
    "/token",
    response_model=TokenResponse,
    responses={
        401: {"description": "Invalid credentials"},
    },
)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> TokenResponse:
    """
    Exchange username + password for a signed JWT access token.

    Accepts `application/x-www-form-urlencoded` with fields:
    - `username`: The demo user's username (e.g. "user-a")
    - `password`: The demo user's password (e.g. "password-a")

    Returns:
        access_token, token_type ("bearer"), tenant_id, and role.

    Raises:
        HTTP 401: If credentials are invalid.
    """
    user = authenticate_user(form_data.username, form_data.password)
    if user is None:
        logger.warning("Failed login attempt for username: %s", form_data.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        username=user.username,
        tenant_id=user.tenant_id,
        role=user.role,
    )

    logger.info(
        "Issued JWT for user '%s' (tenant: %s, role: %s)",
        user.username,
        user.tenant_id,
        user.role,
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        tenant_id=user.tenant_id,
        role=user.role,
    )
