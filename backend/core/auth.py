"""Single-user JWT authentication."""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Cookie, HTTPException, status

from core.config import settings

_ALGORITHM = "HS256"
_TOKEN_EXPIRE_DAYS = 30


def create_token() -> str:
    """Issue a JWT for the single user."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": "user", "iat": now, "exp": now + timedelta(days=_TOKEN_EXPIRE_DAYS)},
        settings.jwt_secret,
        algorithm=_ALGORITHM,
    )


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def require_auth(
    vault_token: str | None = Cookie(default=None),
) -> dict:
    """FastAPI dependency: require valid auth cookie."""
    if not vault_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return verify_token(vault_token)
