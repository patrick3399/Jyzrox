"""Token authentication and rate limiting for the external API."""

import hashlib
import logging
import time

from fastapi import Header, HTTPException
from sqlalchemy import func, text, update

from core.database import async_session
from core.redis_client import get_redis
from db.models import ApiToken

logger = logging.getLogger(__name__)


async def authenticate_token(x_api_token: str, bucket: str, limit: int) -> dict:
    if not x_api_token:
        raise HTTPException(status_code=401, detail="Missing X-API-Token header")

    token_hash = hashlib.sha256(x_api_token.encode()).hexdigest()
    async with async_session() as session:
        result = await session.execute(
            text(
                "SELECT t.id, t.user_id, u.role "
                "FROM api_tokens t JOIN users u ON t.user_id = u.id "
                "WHERE t.token_hash = :hash AND (t.expires_at IS NULL OR t.expires_at > now())"
            ),
            {"hash": token_hash},
        )
        token = result.fetchone()

    if not token:
        raise HTTPException(status_code=401, detail="Invalid or expired API token")

    await check_rate_limit(token.id, bucket, limit)

    # Update last_used_at
    async with async_session() as session:
        await session.execute(update(ApiToken).where(ApiToken.id == token.id).values(last_used_at=func.now()))
        await session.commit()

    return {"user_id": token.user_id, "token_id": token.id, "role": token.role or "viewer"}


async def verify_api_token(x_api_token: str = Header(...)):
    return await authenticate_token(x_api_token, "ext", _RATE_LIMIT_REQUESTS)


async def verify_api_token_for_page_file(x_api_token: str = Header(...)):
    """Token check for page-file downloads, counted in their own bucket.

    A reader requests one file per page, so sharing the metadata budget stalled
    a chapter after about ten pages.
    """
    return await authenticate_token(x_api_token, "ext-file", _FILE_RATE_LIMIT_REQUESTS)


# ── Rate limiter ──────────────────────────────────────────────────────

_RATE_LIMIT_REQUESTS = 10  # max metadata/action requests per window
_FILE_RATE_LIMIT_REQUESTS = 600  # max page-file requests per window
_RATE_LIMIT_WINDOW = 60  # window size in seconds


async def check_rate_limit(token_id: int, bucket: str, limit: int) -> None:
    """Redis-based fixed-window rate limiter scoped to a token and bucket per minute."""
    minute = int(time.time()) // _RATE_LIMIT_WINDOW
    key = f"ratelimit:{bucket}:{token_id}:{minute}"
    r = get_redis()
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, _RATE_LIMIT_WINDOW)
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {limit} requests per minute",
        )
