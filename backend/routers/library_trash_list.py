"""Library split from routers/library.py (library_trash_list)."""

from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_auth, require_role
from core.database import get_db
from core.gallery_helpers import (
    build_cover_map,
)
from db.models import (
    Gallery,
    User,
)
from services.gallery_lifecycle import (
    hard_delete_galleries as _hard_delete_galleries,
)
from services.gallery_lifecycle import (
    restore_galleries,
)
from services.library_helpers import check_write_access as _check_write_access
from services.library_helpers import trash_filter as _trash_filter
from services.library_trash import TrashDirection, TrashReasonFilter, TrashSort
from services.library_trash import queue_purge as _queue_purge
from services.library_trash import trash_item as _trash_item
from services.library_trash import trash_query as _trash_query

_build_cover_map = build_cover_map
_member = require_role("member")
router = APIRouter()


@router.get("/trash/count")
async def trash_count(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return count of soft-deleted galleries."""
    trash_cond = _trash_filter(auth)
    count = (await db.execute(select(func.count()).select_from(Gallery).where(trash_cond))).scalar_one()
    return {"count": count}


@router.get("/trash")
async def list_trash(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=500),
    source: str | None = Query(default=None, max_length=100),
    reason: TrashReasonFilter | None = None,
    sort: TrashSort = "deleted_at",
    direction: TrashDirection = "desc",
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List soft-deleted galleries (trash), optionally filtered and sorted."""
    stmt = _trash_query(auth, q, source, reason, sort, direction)

    total = (await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()

    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()

    cover_map = await _build_cover_map(db, [g.id for g in rows], {g.id: g.source for g in rows})

    user_ids = {g.deleted_by_user_id for g in rows if g.deleted_by_user_id is not None}
    users: dict[int, str] = {}
    if user_ids:
        users = {
            uid: name
            for uid, name in (await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))).all()
        }

    target_ids = {g.merged_into_gallery_id for g in rows if g.merged_into_gallery_id is not None}
    merged: dict[int, Gallery] = {}
    if target_ids:
        targets = (
            (
                await db.execute(
                    select(Gallery).where(
                        Gallery.id.in_(target_ids),
                        Gallery.deleted_at.is_(None),
                        gallery_access_filter(auth),
                    )
                )
            )
            .scalars()
            .all()
        )
        merged = {t.id: t for t in targets}

    return {
        "total": total,
        "galleries": [_trash_item(g, cover_map.get(g.id), users, merged) for g in rows],
    }


@router.post("/galleries/{source}/{source_id}/restore")
async def restore_gallery(
    source: str,
    source_id: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Restore a soft-deleted gallery from trash."""
    source_id = unquote(source_id)
    g = (
        await db.execute(
            select(Gallery).where(
                Gallery.source == source,
                Gallery.source_id == source_id,
                Gallery.deleted_at.is_not(None),
            )
        )
    ).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Gallery not found in trash")
    _check_write_access(auth, g)
    await restore_galleries(db, [g])
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.GALLERY_RESTORED, actor_user_id=auth["user_id"], resource_type="gallery", resource_id=g.id
    )
    return {"status": "ok"}


@router.post("/galleries/{source}/{source_id}/permanent-delete")
async def permanent_delete_gallery(
    source: str,
    source_id: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a gallery (from trash). Irreversible."""
    source_id = unquote(source_id)
    g = (
        await db.execute(
            select(Gallery).where(
                Gallery.source == source,
                Gallery.source_id == source_id,
                Gallery.deleted_at.is_not(None),
            )
        )
    ).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Gallery not found in trash")
    _check_write_access(auth, g)
    result = await _hard_delete_galleries(db, [g])
    return {"status": "ok", **result}


@router.post("/trash/empty", status_code=202)
async def empty_trash(
    q: str | None = Query(default=None, max_length=500),
    source: str | None = Query(default=None, max_length=100),
    reason: TrashReasonFilter | None = None,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Queue permanent deletion of the trashed galleries matching the filter."""
    stmt = _trash_query(auth, q, source, reason).with_only_columns(Gallery.id).order_by(None)
    ids = sorted((await db.execute(stmt)).scalars().all())
    return await _queue_purge(auth, ids)
