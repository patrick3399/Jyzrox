"""Authentication endpoints (session-based, rev 2.0)."""

import json
import bcrypt
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from core.auth import require_auth
from core.config import settings
from core.database import async_session
from core.rate_limit import check_rate_limit, get_client_ip
from core.redis_client import get_redis
from sqlalchemy import text

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)

_SESSION_TTL = 30 * 24 * 3600  # 30 days


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/needs-setup")
async def needs_setup():
    """Check if any users exist. Returns true on first run."""
    async with async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        count = result.scalar()
    return {"needs_setup": count == 0}


@router.post("/setup")
async def setup(req: LoginRequest, request: Request):
    """Create the first admin user. Only works when no users exist."""
    await check_rate_limit(f"setup:{get_client_ip(request)}", max_requests=3, window=60)

    async with async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        if result.scalar() > 0:
            raise HTTPException(status_code=403, detail="Setup already completed")

        password_hash = bcrypt.hashpw(
            req.password.encode("utf-8"), bcrypt.gensalt(rounds=12)
        ).decode("utf-8")
        await session.execute(
            text(
                "INSERT INTO users (username, password_hash, role) "
                "VALUES (:uname, :phash, 'admin')"
            ),
            {"uname": req.username, "phash": password_hash},
        )
        await session.commit()

    return {"status": "ok"}


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    """Login with username/password -> receive httpOnly session cookie."""
    client_ip = get_client_ip(request)
    await check_rate_limit(f"login:{client_ip}")

    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, password_hash, role FROM users WHERE username = :uname"),
            {"uname": req.username},
        )
        user = result.fetchone()

    if not user or not bcrypt.checkpw(
        req.password.encode("utf-8"), user.password_hash.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = secrets.token_urlsafe(32)
    ua = request.headers.get("user-agent", "")
    session_meta = json.dumps({
        "user_id": user.id,
        "role": user.role,
        "ip": client_ip,
        "user_agent": ua[:256],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await get_redis().setex(f"session:{user.id}:{token}", _SESSION_TTL, session_meta)

    response.set_cookie(
        key="vault_session",
        value=f"{user.id}:{token}",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
        max_age=_SESSION_TTL,
    )

    async with async_session() as session:
        await session.execute(
            text("UPDATE users SET last_login_at = now() WHERE id = :uid"), {"uid": user.id}
        )
        await session.commit()

    return {"status": "ok", "role": user.role}


@router.get("/check")
async def check_auth(vault_session: str | None = Cookie(default=None)):
    """Lightweight session validation for nginx auth_request subrequest."""
    if not vault_session:
        raise HTTPException(status_code=401, detail="No session")
    try:
        user_id_str, token = vault_session.split(":", 1)
        session_data = await get_redis().get(f"session:{user_id_str}:{token}")
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid session")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid session")
    return {"status": "ok"}


@router.get("/sessions")
async def list_sessions(
    auth: dict = Depends(require_auth),
    vault_session: str | None = Cookie(default=None),
):
    """List all active sessions for the current user."""
    user_id = auth["user_id"]
    redis = get_redis()
    prefix = f"session:{user_id}:"
    sessions = []

    # Determine current token to mark it
    current_token = ""
    if vault_session:
        try:
            _, current_token = vault_session.split(":", 1)
        except ValueError:
            pass

    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
        for key in keys:
            key_str = key if isinstance(key, str) else key.decode()
            token = key_str[len(prefix):]
            raw = await redis.get(key_str)
            if not raw:
                continue
            ttl = await redis.ttl(key_str)

            # Parse session metadata (could be old format dict-string or new JSON)
            try:
                meta = json.loads(raw if isinstance(raw, str) else raw.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                meta = {}

            sessions.append({
                "token_prefix": token[:8],
                "ip": meta.get("ip", "unknown"),
                "user_agent": meta.get("user_agent", "unknown"),
                "created_at": meta.get("created_at"),
                "ttl": ttl,
                "is_current": token == current_token,
            })
        if cursor == 0:
            break

    # Sort: current first, then by created_at descending
    sessions.sort(key=lambda s: (not s["is_current"], s.get("created_at") or ""), reverse=False)
    return {"sessions": sessions}


@router.delete("/sessions/{token_prefix}")
async def revoke_session(
    token_prefix: str,
    auth: dict = Depends(require_auth),
    vault_session: str | None = Cookie(default=None),
):
    """Revoke a session by its token prefix (first 8 chars)."""
    user_id = auth["user_id"]
    redis = get_redis()
    prefix = f"session:{user_id}:"

    # Determine current token
    current_token = ""
    if vault_session:
        try:
            _, current_token = vault_session.split(":", 1)
        except ValueError:
            pass

    # Find and delete the matching session
    cursor = 0
    deleted = False
    while True:
        cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
        for key in keys:
            key_str = key if isinstance(key, str) else key.decode()
            token = key_str[len(prefix):]
            if token[:8] == token_prefix:
                if token == current_token:
                    raise HTTPException(status_code=400, detail="Cannot revoke current session. Use logout instead.")
                await redis.delete(key_str)
                deleted = True
                break
        if deleted or cursor == 0:
            break

    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"status": "ok"}


@router.post("/logout")
async def logout(
    vault_session: str | None = Cookie(default=None),
    response: Response = None,
):
    """Logout: delete session from Redis and clear cookie."""
    if vault_session:
        try:
            user_id_str, token = vault_session.split(":", 1)
            await get_redis().delete(f"session:{user_id_str}:{token}")
        except ValueError:
            pass

    response.delete_cookie("vault_session", path="/")
    return {"status": "ok"}
