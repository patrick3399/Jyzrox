"""Dedup review and stats API endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update

from core.auth import require_role
from core.database import async_session
from db.models import BlobRelationship
from routers import dedup_review, dedup_scan
from routers.dedup_review import REVIEW_RELATIONSHIPS

router = APIRouter(tags=["dedup"])

_admin = require_role("admin")

router.include_router(dedup_review.router)
router.include_router(dedup_scan.router)


@router.delete("/review/{pair_id}")
async def dismiss_pair(
    pair_id: int,
    _: dict = Depends(_admin),
):
    """Dismiss a pair (mark as resolved)."""
    async with async_session() as session:
        result = await session.execute(select(BlobRelationship).where(BlobRelationship.id == pair_id))
        pair = result.scalar_one_or_none()
        if not pair:
            raise HTTPException(status_code=404, detail="Pair not found")
        if pair.relationship not in REVIEW_RELATIONSHIPS or pair.decision is not None:
            raise HTTPException(status_code=409, detail="Pair is no longer reviewable")

        await session.execute(
            update(BlobRelationship)
            .where(BlobRelationship.id == pair_id)
            .values(
                relationship="decided",
                decision="dismissed",
                decision_by_user_id=_["user_id"],
                decided_at=datetime.now(UTC),
            )
        )
        await session.commit()

    return {"status": "ok"}
