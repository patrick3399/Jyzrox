"""Import conflict-mode, conflict resolution and per-gallery progress endpoints."""

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

import core.queue
from core.auth import require_role
from core.database import async_session
from core.redis_client import get_redis
from db.models import Gallery, ImportConflict

logger = logging.getLogger(__name__)

router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


class ConflictModeRequest(BaseModel):
    mode: str


class ConflictResolutionRequest(BaseModel):
    resolution: str


@router.get("/conflict-mode")
async def get_conflict_mode(_: dict = Depends(_member)):
    value = await get_redis().get("setting:import_conflict_mode")
    if isinstance(value, bytes):
        value = value.decode()
    return {"mode": value or "manual"}


@router.patch("/conflict-mode")
async def set_conflict_mode(body: ConflictModeRequest, _: dict = Depends(_admin)):
    if body.mode not in {"auto_merge", "manual"}:
        raise HTTPException(status_code=400, detail="Invalid import conflict mode")
    await get_redis().set("setting:import_conflict_mode", body.mode)
    return {"mode": body.mode}


@router.get("/conflicts")
async def list_import_conflicts(
    status: str = "pending",
    auth: dict = Depends(_member),
):
    if status not in {"pending", "resolved", "all"}:
        raise HTTPException(status_code=400, detail="Invalid conflict status")
    async with async_session() as session:
        stmt = select(ImportConflict).where(ImportConflict.user_id == auth["user_id"])
        if status != "all":
            stmt = stmt.where(ImportConflict.status == status)
        rows = (await session.execute(stmt.order_by(ImportConflict.created_at.desc()))).scalars().all()
    return {
        "conflicts": [
            {
                "id": row.id,
                "existing_gallery_id": row.existing_gallery_id,
                "source": row.source,
                "source_id": row.source_id,
                "incoming": row.incoming_payload,
                "status": row.status,
                "resolution": row.resolution,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_import_conflict(
    conflict_id: int,
    body: ConflictResolutionRequest,
    auth: dict = Depends(_member),
):
    if body.resolution not in {"merge", "skip"}:
        raise HTTPException(status_code=400, detail="Invalid conflict resolution")
    async with async_session() as session:
        row = (
            await session.execute(
                select(ImportConflict).where(
                    ImportConflict.id == conflict_id,
                    ImportConflict.user_id == auth["user_id"],
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Import conflict not found")
        if row.status != "pending":
            raise HTTPException(status_code=409, detail="Import conflict is already resolved")
        if body.resolution != "skip":
            payload = row.incoming_payload or {}
            path = payload.get("path")
            mode = payload.get("mode")
            if not isinstance(path, str) or mode not in {"copy", "link"} or row.existing_gallery_id is None:
                raise HTTPException(status_code=409, detail="Conflict cannot be resumed")
            await core.queue.enqueue(
                "local_import_job",
                source_dir=path,
                mode=mode,
                gallery_id=row.existing_gallery_id,
            )
        row.status = "resolved"
        row.resolution = body.resolution
        row.resolved_at = datetime.now(UTC)
        await session.commit()
    return {"status": "resolved", "resolution": body.resolution}


@router.get("/progress/{gallery_id}")
async def get_import_progress(
    gallery_id: int,
    auth: dict = Depends(_member),
):
    """Poll import progress for a gallery."""
    # Admin can check any; member only own or unowned galleries
    if auth["role"] != "admin":
        async with async_session() as session:
            gallery = await session.get(Gallery, gallery_id)
            if gallery and gallery.created_by_user_id is not None and gallery.created_by_user_id != auth["user_id"]:
                raise HTTPException(status_code=404, detail="Not found")
    r = get_redis()
    data = await r.get(f"import:progress:{gallery_id}")
    if not data:
        return {"gallery_id": gallery_id, "status": "unknown"}
    return {"gallery_id": gallery_id, **json.loads(data)}
