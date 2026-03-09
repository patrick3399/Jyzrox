"""Authentication endpoints (session-based, rev 2.0)."""

import hashlib
import io
import json
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path

import bcrypt
from fastapi import APIRouter, Cookie, Depends, File, Header, HTTPException, Request, Response, UploadFile
from PIL import Image, ImageOps
from pydantic import BaseModel
from sqlalchemy import text

from core.auth import require_auth
from core.config import settings
from core.database import async_session
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
    await check_rate_limit(f"setup:{get_client_ip(request)}", max_requests=3, window=60)

    async with async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        if result.scalar() > 0:
            raise HTTPException(status_code=403, detail="Setup already completed")

        password_hash = bcrypt.hashpw(req.password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        await session.execute(
            text("INSERT INTO users (username, password_hash, role) VALUES (:uname, :phash, 'admin')"),
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
        # Allow login by username or email
        result = await session.execute(
            text(
                "SELECT id, password_hash, role FROM users "
                "WHERE username = :login OR (email IS NOT NULL AND email = :login)"
            ),
            {"login": req.username},
        )
        user = result.fetchone()

    if not user or not bcrypt.checkpw(req.password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = secrets.token_urlsafe(32)
    ua = request.headers.get("user-agent", "")
    session_meta = json.dumps(
        {
            "user_id": user.id,
            "role": user.role,
            "ip": client_ip,
            "user_agent": ua[:256],
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    await get_redis().setex(f"session:{user.id}:{token}", _SESSION_TTL, session_meta)

    is_https = _is_https(request)
    response.set_cookie(
        key="vault_session",
        value=f"{user.id}:{token}",
        httponly=True,
        secure=settings.cookie_secure and is_https,
        samesite="strict" if is_https else "lax",
        path="/",
        max_age=_SESSION_TTL,
    )

    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=settings.cookie_secure and is_https,
        samesite="strict" if is_https else "lax",
        path="/",
        max_age=_SESSION_TTL,
    )

    async with async_session() as session:
        await session.execute(text("UPDATE users SET last_login_at = now() WHERE id = :uid"), {"uid": user.id})
        await session.commit()

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
            if user and bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
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

            # Parse session metadata (could be old format dict-string or new JSON)
            try:
                meta = json.loads(raw if isinstance(raw, str) else raw.decode())
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
    response.delete_cookie("csrf_token", path="/")
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
        valid_locales = ("en", "zh-TW", "ja", "ko")
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
    except (OSError, ValueError) as exc:
        logger.warning("Avatar upload failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid image file")

    avatars_dir = Path(settings.data_avatars_path)
    avatars_dir.mkdir(parents=True, exist_ok=True)
    out_path = avatars_dir / f"{auth['user_id']}.webp"
    tmp_path = out_path.with_suffix(".webp.tmp")
    img.save(str(tmp_path), "WEBP", quality=85)
    tmp_path.replace(out_path)

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
async def change_password(req: ChangePasswordRequest, auth: dict = Depends(require_auth)):
    """Change the current user's password."""
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    async with async_session() as session:
        result = await session.execute(
            text("SELECT password_hash FROM users WHERE id = :uid"),
            {"uid": auth["user_id"]},
        )
        user = result.fetchone()

    if not user or not bcrypt.checkpw(req.current_password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_hash = bcrypt.hashpw(req.new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    async with async_session() as session:
        await session.execute(
            text("UPDATE users SET password_hash = :phash WHERE id = :uid"),
            {"phash": new_hash, "uid": auth["user_id"]},
        )
        await session.commit()

    return {"status": "ok"}
