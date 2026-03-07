"""Single-user authentication endpoints (Basic Auth rev 2.0)."""

import bcrypt
import logging
import secrets
from fastapi import APIRouter, HTTPException, Response, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from core.database import async_session
from sqlalchemy import text
from core.redis_client import get_redis

router = APIRouter(tags=["auth"])
security = HTTPBasic()
logger = logging.getLogger(__name__)

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
async def login(req: LoginRequest, response: Response):
    """Login with username/password → receive httpOnly session cookie."""
    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, password_hash, role FROM users WHERE username = :uname"),
            {"uname": req.username}
        )
        user = result.fetchone()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # verify bcrypt
    if not bcrypt.checkpw(req.password.encode('utf-8'), user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # create session token
    token = secrets.token_urlsafe(32)
    session_data = {"user_id": user.id, "role": user.role}
    
    # Store in Redis: session:{user_id}:{token}
    await get_redis().setex(f"session:{user.id}:{token}", 30 * 24 * 3600, str(session_data))

    response.set_cookie(
        key="vault_session",
        value=f"{user.id}:{token}",
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )

    # update last_login
    async with async_session() as session:
        await session.execute(text("UPDATE users SET last_login_at = now() WHERE id = :uid"), {"uid": user.id})
        await session.commit()

    return {"status": "ok", "role": user.role}

@router.post("/logout")
async def logout(response: Response):
    # Depending on how the cookie is read, we might want to also delete from redis here.
    # For now simply delete the cookie.
    response.delete_cookie("vault_session")
    return {"status": "ok"}

