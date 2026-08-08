"""
Local JWT authentication service.

Provides:
- In-memory demo user store (bcrypt-hashed passwords at startup).
- Password verification via passlib[bcrypt].
- JWT creation and decoding via PyJWT.

This is a self-contained local auth layer — no external identity
provider is required. Suitable for development and demo use.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, status

from app.config import settings
from app.seed import DEMO_USERS

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Password hashing (bcrypt directly — passlib 1.7.x is incompatible with bcrypt 5.x)
# ──────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt."""
    # bcrypt requires bytes; use a work factor of 12 for demo security
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ──────────────────────────────────────────────
# In-memory user store
# ──────────────────────────────────────────────

@dataclass
class DemoUser:
    """Represents an in-memory demo user."""
    username: str
    hashed_password: str
    tenant_id: str
    role: str  # "user" | "admin"


def _build_user_store() -> dict[str, DemoUser]:
    """
    Build the in-memory user store from the DEMO_USERS seed list.

    Passwords are bcrypt-hashed here at startup — the plaintext
    from DEMO_USERS is never persisted anywhere.
    """
    store: dict[str, DemoUser] = {}
    for entry in DEMO_USERS:
        username = entry["username"]
        store[username] = DemoUser(
            username=username,
            hashed_password=hash_password(entry["password"]),
            tenant_id=entry["tenant_id"],
            role=entry.get("role", "user"),
        )
        logger.info("Demo user registered: %s (tenant: %s)", username, entry["tenant_id"])
    return store


# Module-level singleton — built once when auth.py is first imported
_USER_STORE: dict[str, DemoUser] = _build_user_store()


def authenticate_user(username: str, password: str) -> Optional[DemoUser]:
    """
    Authenticate a user by username and password.

    Args:
        username: The username to look up.
        password: The plaintext password to verify.

    Returns:
        DemoUser if credentials are valid, None otherwise.
    """
    user = _USER_STORE.get(username)
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# ──────────────────────────────────────────────
# JWT helpers
# ──────────────────────────────────────────────

def create_access_token(
    username: str,
    tenant_id: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    The token payload contains:
    - sub: username (standard JWT subject claim)
    - tenant_id: the tenant this user belongs to
    - role: user role ("user" | "admin")
    - exp: expiry timestamp

    Args:
        username: The authenticated username.
        tenant_id: The tenant the user belongs to.
        role: The user's role.
        expires_delta: Custom expiry. Defaults to settings.jwt_access_token_expire_minutes.

    Returns:
        Signed JWT string.

    Raises:
        RuntimeError: If JWT_SECRET_KEY is not configured.
    """
    if not settings.jwt_secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Add it to your .env file before using authentication."
        )

    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": username,
        "tenant_id": tenant_id,
        "role": role,
        "exp": expire,
    }

    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT access token.

    Args:
        token: The raw JWT string from the Authorization header.

    Returns:
        The decoded payload dict containing sub, tenant_id, role, exp.

    Raises:
        HTTPException 401: If the token is invalid, expired, or missing required claims.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token has expired")
        raise credentials_exc
    except jwt.InvalidTokenError as exc:
        logger.warning("JWT decode error: %s", exc)
        raise credentials_exc

    # Ensure required claims are present
    if not payload.get("tenant_id"):
        logger.warning("JWT missing tenant_id claim")
        raise credentials_exc

    return payload
