"""Authentication endpoints (session-based, rev 2.0)."""

import bcrypt
import logging
import secrets
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from core.database import async_session
from sqlalchemy import text
from core.redis_client import get_redis

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
async def setup(req: LoginRequest):
    """Create the first admin user. Only works when no users exist."""
    async with async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        if result.scalar() > 0:
            raise HTTPException(status_code=403, detail="Setup already completed")

        password_hash = bcrypt.hashpw(
            req.password.encode("utf-8"), bcrypt.gensalt()
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
async def login(req: LoginRequest, response: Response):
    """Login with username/password → receive httpOnly session cookie."""
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
    await get_redis().setex(
        f"session:{user.id}:{token}", _SESSION_TTL, str({"user_id": user.id, "role": user.role})
    )

    response.set_cookie(
        key="vault_session",
        value=f"{user.id}:{token}",
        httponly=True,
        samesite="lax",
        max_age=_SESSION_TTL,
    )

    async with async_session() as session:
        await session.execute(
            text("UPDATE users SET last_login_at = now() WHERE id = :uid"), {"uid": user.id}
        )
        await session.commit()

    return {"status": "ok", "role": user.role}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("vault_session")
    return {"status": "ok"}

