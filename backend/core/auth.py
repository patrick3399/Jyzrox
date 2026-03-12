"""Session-based authentication (Redis)."""

import base64
import binascii
import hashlib
import hmac
import json
import logging

import bcrypt
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import text

from core.config import settings
from core.database import async_session
from core.errors import api_error, parse_accept_language
from core.redis_client import get_redis

logger = logging.getLogger(__name__)

# Role hierarchy: higher number = more permissions
ROLE_HIERARCHY = {"admin": 3, "member": 2, "viewer": 1}

# Pre-computed dummy hash to prevent timing attacks on username enumeration.
# bcrypt.checkpw() is always called regardless of whether the user exists.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-constant-timing", bcrypt.gensalt(rounds=12)).decode()


def _sign_session(data: str) -> str:
    """Append HMAC-SHA256 signature to session metadata string."""
    sig = hmac.new(settings.credential_encrypt_key.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}:{sig}"


def _verify_session(raw: str) -> str | None:
    """Verify HMAC signature and return the original data, or None on failure.

    Returns the data portion without the signature.  For backward-compat,
    if the raw value contains no ':'-separated signature segment that looks
    like a 64-char hex digest, the data is returned as-is with a warning so
    that existing sessions are not immediately invalidated after deployment.
    """
    idx = raw.rfind(":")
    if idx == -1:
        # No separator at all — treat as unsigned legacy session
        logger.warning("Session data has no HMAC signature (legacy session); treating as valid")
        return raw
    data, sig = raw[:idx], raw[idx + 1:]
    # A SHA-256 hex digest is always 64 characters
    if len(sig) != 64:
        # Looks like the ':' was part of the JSON, not a signature separator — legacy session
        logger.warning("Session data appears to be an unsigned legacy session; treating as valid")
        return raw
    expected = hmac.new(settings.credential_encrypt_key.encode(), data.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return data
    logger.warning("Session HMAC signature mismatch — possible tampering")
    return None


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

    redis_key = f"session:{user_id_str}:{token}"

    # Verify HMAC signature and parse role from session metadata
    role = "viewer"  # safe default
    try:
        raw_bytes = session_data if isinstance(session_data, str) else session_data.decode()
        verified = _verify_session(raw_bytes)
        if verified is None:
            logger.warning("Session signature verification failed for key %s", redis_key)
            raise api_error(status.HTTP_401_UNAUTHORIZED, "session_invalid", locale)
        meta = json.loads(verified)
        if isinstance(meta, dict):
            role = meta.get("role", "viewer")
            # #17: Warn (but do not reject) on IP/UA mismatch to detect session hijacking
            stored_ip = meta.get("ip")
            stored_ua = meta.get("user_agent", "")
            current_ip = request.client.host if request.client else None
            current_ua = request.headers.get("user-agent", "")
            if stored_ip and current_ip and stored_ip != current_ip:
                logger.warning(
                    "Session IP mismatch for user %s: stored=%s current=%s",
                    user_id_str, stored_ip, current_ip,
                )
            if stored_ua and current_ua and stored_ua != current_ua[:256]:
                logger.warning(
                    "Session UA mismatch for user %s",
                    user_id_str,
                )
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
        logger.warning("Corrupted session data for %s: %s", redis_key, e)
        raise api_error(status.HTTP_401_UNAUTHORIZED, "session_invalid", locale)

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

    # Always call checkpw to prevent timing-based username enumeration.
    hash_to_check = user.password_hash if user else _DUMMY_HASH
    valid = bcrypt.checkpw(password.encode("utf-8"), hash_to_check.encode("utf-8"))
    if not user or not valid:
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
