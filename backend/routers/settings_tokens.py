"""Settings: API tokens."""

import hashlib
import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from core.auth import require_role
from core.database import async_session

logger = logging.getLogger(__name__)
router = APIRouter()

_admin = require_role("admin")
_member = require_role("member")


class CreateTokenRequest(BaseModel):
    name: str
    expires_days: int | None = None  # None = never expires


@router.get("/tokens")
async def list_tokens(auth: dict = Depends(_member)):
    """List all API tokens for the current user."""
    async with async_session() as session:
        rows = await session.execute(
            text("""
                SELECT id, name, token_hash, created_at, last_used_at, expires_at
                FROM api_tokens
                WHERE user_id = :uid
                ORDER BY created_at DESC
            """),
            {"uid": auth["user_id"]},
        )
    tokens = []
    for r in rows:
        tokens.append(
            {
                "id": str(r.id),
                "name": r.name,
                "token_prefix": r.token_hash[:8],
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
        )
    return {"tokens": tokens}


_MAX_TOKEN_EXPIRY_DAYS = 365


@router.post("/tokens")
async def create_token(
    req: CreateTokenRequest,
    auth: dict = Depends(_member),
):
    """Create a new API token."""
    if req.expires_days is not None and req.expires_days > _MAX_TOKEN_EXPIRY_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"expires_days must be <= {_MAX_TOKEN_EXPIRY_DAYS}",
        )

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    expires_at = None
    if req.expires_days and req.expires_days > 0:
        from datetime import timedelta

        expires_at = datetime.now(UTC) + timedelta(days=req.expires_days)

    async with async_session() as session:
        result = await session.execute(
            text("""
                INSERT INTO api_tokens (user_id, name, token_hash, expires_at)
                VALUES (:uid, :name, :hash, :exp)
                RETURNING id, created_at
            """),
            {
                "uid": auth["user_id"],
                "name": req.name.strip(),
                "hash": token_hash,
                "exp": expires_at,
            },
        )
        row = result.fetchone()
        await session.commit()

    return {
        "id": str(row.id),
        "name": req.name.strip(),
        "token": raw_token,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


@router.delete("/tokens/{token_id}")
async def delete_token(
    token_id: str,
    auth: dict = Depends(_member),
):
    """Revoke/delete an API token."""
    async with async_session() as session:
        result = await session.execute(
            text("DELETE FROM api_tokens WHERE id = :id AND user_id = :uid RETURNING id"),
            {"id": token_id, "uid": auth["user_id"]},
        )
        deleted = result.fetchone()
        await session.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "ok"}


@router.patch("/tokens/{token_id}")
async def update_token(
    token_id: str,
    name: str = Query(default=None),
    auth: dict = Depends(_member),
):
    """Update token name."""
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    async with async_session() as session:
        result = await session.execute(
            text("UPDATE api_tokens SET name = :name WHERE id = :id AND user_id = :uid RETURNING id"),
            {"name": name.strip(), "id": token_id, "uid": auth["user_id"]},
        )
        updated = result.fetchone()
        await session.commit()

    if not updated:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "ok"}
