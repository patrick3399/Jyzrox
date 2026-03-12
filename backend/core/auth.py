"""Session-based authentication (Redis)."""

import base64
import binascii
import json

import bcrypt
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import text

from core.database import async_session
from core.errors import api_error, parse_accept_language
from core.redis_client import get_redis

# Role hierarchy: higher number = more permissions
ROLE_HIERARCHY = {"admin": 3, "member": 2, "viewer": 1}


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

    # Parse role from session metadata
    role = "viewer"  # safe default
    try:
        raw = session_data if isinstance(session_data, str) else session_data.decode()
        meta = json.loads(raw)
        if isinstance(meta, dict):
            role = meta.get("role", "viewer")
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        pass

    return {"user_id": int(user_id_str), "role": role}


def require_role(*allowed_roles: str):
    """Factory: returns a FastAPI dependency that checks role >= min required level."""
    min_level = min(ROLE_HIERARCHY.get(r, 0) for r in allowed_roles)

    async def _check(request: Request, auth: dict = Depends(require_auth)) -> dict:
        user_level = ROLE_HIERARCHY.get(auth.get("role", ""), 0)
        if user_level < min_level:
            locale = parse_accept_language(request.headers.get("accept-language"))
            raise api_error(status.HTTP_403_FORBIDDEN, "forbidden", locale)
        return auth

    return _check


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
        raw = base64.b64decode(authorization[6:])
    except binascii.Error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header: base64 decode failed",
            headers={"WWW-Authenticate": 'Basic realm="Jyzrox OPDS"'},
        )

    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header: credentials must be UTF-8",
            headers={"WWW-Authenticate": 'Basic realm="Jyzrox OPDS"'},
        )

    if ":" not in decoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header: missing username:password separator",
            headers={"WWW-Authenticate": 'Basic realm="Jyzrox OPDS"'},
        )

    username, password = decoded.split(":", 1)

    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, password_hash, role FROM users WHERE username = :uname"),
            {"uname": username},
        )
        user = result.fetchone()

    if not user or not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="Jyzrox OPDS"'},
        )

    return {"user_id": user.id, "role": user.role or "viewer"}


def gallery_access_filter(auth: dict):
    """Return SQLAlchemy WHERE clause for gallery visibility based on user role.

    Admin sees everything. Non-admin sees own + system + public galleries.
    Import: from core.auth import gallery_access_filter
    Usage: stmt = stmt.where(gallery_access_filter(auth))
    """
    from sqlalchemy import or_
    from db.models import Gallery

    if auth.get("role") == "admin":
        return Gallery.id.isnot(None)  # always-true condition
    user_id = auth["user_id"]
    return or_(
        Gallery.created_by_user_id == user_id,
        Gallery.created_by_user_id.is_(None),
        Gallery.visibility == "public",
    )
