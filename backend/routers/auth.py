"""Authentication endpoints (session-based, rev 2.0)."""

import asyncio
import hashlib
import io
import json
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path

import bcrypt
from fastapi import APIRouter, Cookie, Depends, File, Header, HTTPException, Request, Response, UploadFile
from starlette import status
from PIL import Image, ImageOps
from pydantic import BaseModel
from sqlalchemy import text

from core.audit import log_audit
from core.auth import _DUMMY_HASH, _sign_session, _verify_session, require_auth
from core.config import settings
from core.database import async_session
from core.errors import api_error, parse_accept_language
from core.rate_limit import check_rate_limit, get_client_ip
from core.redis_client import get_redis

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)

_SESSION_TTL = 30 * 24 * 3600  # 30 days


def _is_https(request: Request) -> bool:
    """Detect if the client connection is over HTTPS (direct or via reverse proxy)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.lower() == "https"


class LoginRequest(BaseModel):
    username: str  # accepts username or email
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    email: str | None = None
    avatar_style: str | None = None
    locale: str | None = None


def _avatar_url(user_id: int, username: str, email: str | None, avatar_style: str) -> str:
    if avatar_style == "manual":
        return f"/media/avatars/{user_id}.webp"
    digest = hashlib.md5((email or username).lower().encode()).hexdigest()
    return f"https://www.gravatar.com/avatar/{digest}?d=retro&s=160"


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
    await check_rate_limit(f"setup:{get_client_ip(request)}", max_requests=3, window=3600)

    async with async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        if result.scalar() > 0:
            locale = parse_accept_language(request.headers.get("accept-language"))
            raise api_error(403, "setup_completed", locale)

        password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        result = await session.execute(
            text("""
                INSERT INTO users (username, password_hash, role)
                SELECT :uname, :phash, 'admin'
                WHERE NOT EXISTS (SELECT 1 FROM users)
            """),
            {"uname": req.username, "phash": password_hash},
        )
        if result.rowcount == 0:
            locale = parse_accept_language(request.headers.get("accept-language"))
            raise api_error(status.HTTP_403_FORBIDDEN, "setup_completed", locale)
        await session.commit()

    # Fetch the new user's id for audit logging
    async with async_session() as session:
        result = await session.execute(
            text("SELECT id FROM users WHERE username = :uname"),
            {"uname": req.username},
        )
        new_user = result.fetchone()
    await log_audit(new_user.id if new_user else None, "setup", ip=get_client_ip(request))
    return {"status": "ok"}


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    """Login with username/password -> receive httpOnly session cookie."""
    client_ip = get_client_ip(request)
    await check_rate_limit(f"login:{client_ip}")

    async with async_session() as session:
        # Allow login by username or email
        result = await session.execute(
            text(
                "SELECT id, password_hash, role FROM users "
                "WHERE username = :login OR (email IS NOT NULL AND email = :login)"
            ),
            {"login": req.username},
        )
        user = result.fetchone()

    # Always call checkpw to prevent timing-based username enumeration.
    hash_to_check = user.password_hash if user else _DUMMY_HASH
    valid = bcrypt.checkpw(req.password.encode("utf-8"), hash_to_check.encode("utf-8"))
    if not user or not valid:
        await log_audit(None, "login_failed", detail=f"username={req.username}", ip=client_ip)
        raise api_error(401, "invalid_credentials", parse_accept_language(request.headers.get("accept-language")))

    token = secrets.token_urlsafe(32)
    ua = request.headers.get("user-agent", "")
    session_meta = _sign_session(json.dumps(
        {
            "user_id": user.id,
            "role": user.role,
            "ip": client_ip,
            "user_agent": ua[:256],
            "created_at": datetime.now(UTC).isoformat(),
        }
    ))
    await get_redis().setex(f"session:{user.id}:{token}", _SESSION_TTL, session_meta)

    is_https = _is_https(request)
    response.set_cookie(
        key="vault_session",
        value=f"{user.id}:{token}",
        httponly=True,
        secure=settings.cookie_secure and is_https,
        samesite="strict",
        path="/",
        max_age=_SESSION_TTL,
    )

    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=settings.cookie_secure and is_https,
        samesite="strict",
        path="/",
        max_age=_SESSION_TTL,
    )

    async with async_session() as session:
        await session.execute(text("UPDATE users SET last_login_at = now() WHERE id = :uid"), {"uid": user.id})
        await session.commit()

    await log_audit(user.id, "login_success", ip=client_ip)
    return {"status": "ok", "role": user.role}


@router.get("/check")
async def check_auth(
    vault_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
):
    """Lightweight session validation for nginx auth_request subrequest."""
    # Try cookie first (existing logic)
    if vault_session:
        try:
            user_id_str, token = vault_session.split(":", 1)
            session_data = await get_redis().get(f"session:{user_id_str}:{token}")
            if session_data:
                return {"status": "ok"}
        except ValueError:
            pass

    # Fallback to Basic Auth (for OPDS clients)
    if authorization and authorization.lower().startswith("basic "):
        import base64
        try:
            decoded = base64.b64decode(authorization[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            async with async_session() as session:
                result = await session.execute(
                    text("SELECT id, password_hash FROM users WHERE username = :uname"),
                    {"uname": username},
                )
                user = result.fetchone()
            hash_to_check = user.password_hash if user else _DUMMY_HASH
            if user and bcrypt.checkpw(password.encode("utf-8"), hash_to_check.encode("utf-8")):
                return {"status": "ok"}
        except Exception:
            pass

    raise HTTPException(status_code=401, detail="Not authenticated")


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
            token = key_str[len(prefix) :]
            raw = await redis.get(key_str)
            if not raw:
                continue
            ttl = await redis.ttl(key_str)

            # Parse session metadata — strip HMAC signature before JSON parsing
            try:
                raw_str = raw if isinstance(raw, str) else raw.decode()
                verified = _verify_session(raw_str)
                meta = json.loads(verified) if verified else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                meta = {}

            sessions.append(
                {
                    "token_prefix": token[:8],
                    "ip": meta.get("ip", "unknown"),
                    "user_agent": meta.get("user_agent", "unknown"),
                    "created_at": meta.get("created_at"),
                    "ttl": ttl,
                    "is_current": token == current_token,
                }
            )
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
            token = key_str[len(prefix) :]
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
    request: Request,
    vault_session: str | None = Cookie(default=None),
    response: Response = None,
):
    """Logout: delete session from Redis and clear cookie."""
    logged_user_id: int | None = None
    if vault_session:
        try:
            user_id_str, token = vault_session.split(":", 1)
            logged_user_id = int(user_id_str)
            await get_redis().delete(f"session:{user_id_str}:{token}")
        except ValueError:
            pass

    response.delete_cookie("vault_session", path="/")
    response.delete_cookie("csrf_token", path="/")
    await log_audit(logged_user_id, "logout", ip=get_client_ip(request))
    return {"status": "ok"}


@router.get("/profile")
async def get_profile(auth: dict = Depends(require_auth)):
    """Return current user's profile info."""
    async with async_session() as session:
        result = await session.execute(
            text("SELECT username, email, role, created_at, avatar_style, locale FROM users WHERE id = :uid"),
            {"uid": auth["user_id"]},
        )
        user = result.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    avatar_style = user.avatar_style or "gravatar"
    return {
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "avatar_style": avatar_style,
        "avatar_url": _avatar_url(auth["user_id"], user.username, user.email, avatar_style),
        "locale": user.locale,
    }


@router.patch("/profile")
async def update_profile(req: UpdateProfileRequest, auth: dict = Depends(require_auth)):
    """Update current user's profile (email, avatar_style)."""
    update_values: dict = {}

    if req.email is not None:
        email = req.email.strip() or None
        if email:
            async with async_session() as session:
                existing = await session.execute(
                    text("SELECT id FROM users WHERE email = :email AND id != :uid"),
                    {"email": email, "uid": auth["user_id"]},
                )
                if existing.fetchone():
                    raise HTTPException(status_code=409, detail="Email already in use")
        update_values["email"] = email

    if req.avatar_style is not None:
        if req.avatar_style not in ("gravatar", "manual"):
            raise HTTPException(status_code=400, detail="avatar_style must be 'gravatar' or 'manual'")
        update_values["avatar_style"] = req.avatar_style

    if req.locale is not None:
        valid_locales = ("en", "zh-TW", "zh-CN", "ja", "ko")
        if req.locale not in valid_locales:
            raise HTTPException(status_code=400, detail=f"locale must be one of: {', '.join(valid_locales)}")
        update_values["locale"] = req.locale

    if not update_values:
        return {"status": "ok"}

    # Build parameterized SET clause from known column names
    set_parts = [f"{col} = :{col}" for col in update_values]
    update_values["uid"] = auth["user_id"]
    async with async_session() as session:
        await session.execute(
            text(f"UPDATE users SET {', '.join(set_parts)} WHERE id = :uid"),
            update_values,
        )
        await session.commit()
    return {"status": "ok"}


_MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB


@router.put("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    auth: dict = Depends(require_auth),
):
    """Upload a custom avatar image. Resized to 160x160 WebP."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are accepted")

    data = await file.read()
    if len(data) > _MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 2 MB)")

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.fit(img, (160, 160))
        img = img.convert("RGB")
    except Exception as exc:
        logger.warning("Avatar upload failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid image file")

    avatars_dir = Path(settings.data_avatars_path)
    avatars_dir.mkdir(parents=True, exist_ok=True)
    out_path = avatars_dir / f"{auth['user_id']}.webp"
    tmp_path = out_path.with_suffix(".webp.tmp")
    await asyncio.to_thread(img.save, str(tmp_path), "WEBP", quality=85)
    await asyncio.to_thread(tmp_path.replace, out_path)

    async with async_session() as session:
        await session.execute(
            text("UPDATE users SET avatar_style = 'manual' WHERE id = :uid"),
            {"uid": auth["user_id"]},
        )
        await session.commit()

    return {
        "status": "ok",
        "avatar_url": f"/media/avatars/{auth['user_id']}.webp",
        "avatar_style": "manual",
    }


@router.delete("/avatar")
async def delete_avatar(auth: dict = Depends(require_auth)):
    """Remove custom avatar and revert to Gravatar."""
    avatar_file = Path(settings.data_avatars_path) / f"{auth['user_id']}.webp"
    if avatar_file.exists():
        avatar_file.unlink()

    async with async_session() as session:
        await session.execute(
            text("UPDATE users SET avatar_style = 'gravatar' WHERE id = :uid"),
            {"uid": auth["user_id"]},
        )
        result = await session.execute(
            text("SELECT username, email FROM users WHERE id = :uid"),
            {"uid": auth["user_id"]},
        )
        user = result.fetchone()
        await session.commit()

    avatar_url = _avatar_url(auth["user_id"], user.username, user.email, "gravatar") if user else ""
    return {"status": "ok", "avatar_url": avatar_url, "avatar_style": "gravatar"}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    auth: dict = Depends(require_auth),
    vault_session: str | None = Cookie(default=None),
):
    """Change the current user's password and invalidate all other sessions."""
    await check_rate_limit(f"password_change:{auth['user_id']}", max_requests=3, window=300)

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    async with async_session() as session:
        result = await session.execute(
            text("SELECT password_hash FROM users WHERE id = :uid"),
            {"uid": auth["user_id"]},
        )
        user = result.fetchone()

    # Always call checkpw to prevent timing attacks.
    hash_to_check = user.password_hash if user else _DUMMY_HASH
    valid = bcrypt.checkpw(req.current_password.encode("utf-8"), hash_to_check.encode("utf-8"))
    if not user or not valid:
        await log_audit(auth["user_id"], "password_change_failed", ip=get_client_ip(request))
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_hash = bcrypt.hashpw(req.new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    async with async_session() as session:
        await session.execute(
            text("UPDATE users SET password_hash = :phash WHERE id = :uid"),
            {"phash": new_hash, "uid": auth["user_id"]},
        )
        await session.commit()

    # Invalidate all other sessions for this user (keep only the current one).
    current_token = ""
    if vault_session:
        try:
            _, current_token = vault_session.split(":", 1)
        except ValueError:
            pass

    redis = get_redis()
    user_id = auth["user_id"]
    prefix = f"session:{user_id}:"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
        for key in keys:
            key_str = key if isinstance(key, str) else key.decode()
            token = key_str[len(prefix):]
            if token != current_token:
                await redis.delete(key_str)
        if cursor == 0:
            break

    await log_audit(auth["user_id"], "password_changed", ip=get_client_ip(request))
    return {"status": "ok"}
