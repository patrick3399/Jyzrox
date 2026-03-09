"""Session-based authentication (Redis)."""

import base64

import bcrypt
from fastapi import Cookie, Header, HTTPException, Request, status
from sqlalchemy import text

from core.database import async_session
from core.errors import api_error, parse_accept_language
from core.redis_client import get_redis


async def require_auth(
    request: Request,
    vault_session: str | None = Cookie(default=None),
) -> dict:
    """FastAPI dependency: require valid session cookie."""
    locale = parse_accept_language(request.headers.get("accept-language"))

    if not vault_session:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "not_authenticated", locale)

    try:
        user_id_str, token = vault_session.split(":", 1)
    except ValueError:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "session_invalid", locale)

    session_data = await get_redis().get(f"session:{user_id_str}:{token}")
    if not session_data:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "session_expired", locale)

    return {"user_id": int(user_id_str)}


async def require_opds_auth(
    authorization: str | None = Header(default=None),
) -> dict:
    """FastAPI dependency: require HTTP Basic Auth for OPDS endpoints."""
    if not authorization or not authorization.lower().startswith("basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": 'Basic realm="Jyzrox OPDS"'},
        )

    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header",
            headers={"WWW-Authenticate": 'Basic realm="Jyzrox OPDS"'},
        )

    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, password_hash FROM users WHERE username = :uname"),
            {"uname": username},
        )
        user = result.fetchone()

    if not user or not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Jyzrox OPDS"'},
        )

    return {"user_id": user.id}
