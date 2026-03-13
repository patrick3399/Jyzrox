"""User management (admin only)."""

import json
import logging

import bcrypt
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from core.auth import _checkpw_async, _hashpw_async, _sign_session, _verify_session, require_role
from core.database import get_db
from core.errors import api_error, parse_accept_language
from core.redis_client import get_redis
from db.models import User

router = APIRouter(tags=["users"])
logger = logging.getLogger(__name__)

_admin = require_role("admin")


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "member"
    email: str | None = None


class UpdateUserRequest(BaseModel):
    role: str | None = None
    email: str | None = None
    password: str | None = None


@router.get("/")
async def list_users(
    auth: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).order_by(User.id)
    )
    users = result.scalars().all()
    return {"users": [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        }
        for u in users
    ]}


@router.post("/", status_code=201)
async def create_user(
    req: CreateUserRequest,
    request: Request,
    auth: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    locale = parse_accept_language(request.headers.get("accept-language"))

    if req.role not in ("admin", "member", "viewer"):
        raise api_error(status.HTTP_400_BAD_REQUEST, "invalid_request", locale)

    if len(req.password) < 8:
        raise api_error(status.HTTP_400_BAD_REQUEST, "invalid_request", locale)

    # Check username uniqueness
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalars().first():
        raise api_error(status.HTTP_409_CONFLICT, "username_taken", locale)

    password_hash = (await _hashpw_async(req.password.encode("utf-8"), bcrypt.gensalt(rounds=12))).decode("utf-8")

    user = User(
        username=req.username,
        password_hash=password_hash,
        role=req.role,
        email=req.email,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "email": user.email,
    }


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    request: Request,
    auth: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    locale = parse_accept_language(request.headers.get("accept-language"))

    user = await db.get(User, user_id)
    if not user:
        raise api_error(status.HTTP_404_NOT_FOUND, "user_not_found", locale)

    if req.role is not None:
        if req.role not in ("admin", "member", "viewer"):
            raise api_error(status.HTTP_400_BAD_REQUEST, "invalid_request", locale)
        # Prevent demoting the last admin
        if user.role == "admin" and req.role != "admin":
            result = await db.execute(
                select(func.count()).select_from(User).where(User.role == "admin")
            )
            if result.scalar() <= 1:
                raise api_error(status.HTTP_400_BAD_REQUEST, "cannot_delete_last_admin", locale)
        user.role = req.role

    if req.email is not None:
        user.email = req.email.strip() or None

    if req.password is not None:
        if len(req.password) < 8:
            raise api_error(status.HTTP_400_BAD_REQUEST, "invalid_request", locale)
        user.password_hash = (await _hashpw_async(
            req.password.encode("utf-8"), bcrypt.gensalt(rounds=12)
        )).decode("utf-8")

    await db.commit()

    # Immediately update role in all active sessions for this user.
    # If Redis is unavailable, delete all sessions to force re-login and
    # prevent the old role from persisting for up to 30 days.
    if req.role is not None:
        redis = get_redis()
        prefix = f"session:{user_id}:"
        try:
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
                for key in keys:
                    key_str = key if isinstance(key, str) else key.decode()
                    raw = await redis.get(key_str)
                    if not raw:
                        continue
                    ttl = await redis.ttl(key_str)
                    if ttl < 1:
                        continue
                    try:
                        raw_str = raw if isinstance(raw, str) else raw.decode()
                        verified = _verify_session(raw_str)
                        if verified is None:
                            await redis.delete(key_str)
                            continue
                        data = json.loads(verified)
                        data["role"] = req.role
                        await redis.setex(key_str, ttl, _sign_session(json.dumps(data)))
                    except (json.JSONDecodeError, TypeError):
                        pass
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning(
                "Redis unavailable when updating role for user %d (%s); "
                "deleting all sessions to force re-login",
                user_id,
                exc,
            )
            try:
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
                    for key in keys:
                        key_str = key if isinstance(key, str) else key.decode()
                        await redis.delete(key_str)
                    if cursor == 0:
                        break
            except Exception as del_exc:
                logger.error(
                    "Failed to delete sessions for user %d during role update: %s",
                    user_id,
                    del_exc,
                )

    return {"status": "ok"}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    auth: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    locale = parse_accept_language(request.headers.get("accept-language"))

    if user_id == auth["user_id"]:
        raise api_error(status.HTTP_400_BAD_REQUEST, "cannot_delete_self", locale)

    user = await db.get(User, user_id)
    if not user:
        raise api_error(status.HTTP_404_NOT_FOUND, "user_not_found", locale)

    # Check if this is the last admin
    if user.role == "admin":
        result = await db.execute(
            select(func.count()).select_from(User).where(User.role == "admin")
        )
        admin_count = result.scalar()
        if admin_count <= 1:
            raise api_error(status.HTTP_400_BAD_REQUEST, "cannot_delete_last_admin", locale)

    # Delete all sessions for this user from Redis
    redis = get_redis()
    prefix = f"session:{user_id}:"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
        for key in keys:
            await redis.delete(key if isinstance(key, str) else key.decode())
        if cursor == 0:
            break

    await db.delete(user)
    await db.commit()
    return {"status": "ok"}
