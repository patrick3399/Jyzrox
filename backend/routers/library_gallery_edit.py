"""Library split from routers/library.py (library_gallery_edit)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_role
from core.database import get_db
from db.models import (
    UserFavorite,
    UserRating,
    UserReadingList,
)
from services.gallery_lifecycle import (
    hard_delete_galleries as _hard_delete_galleries,
)
from services.gallery_lifecycle import (
    invalidate_sources_cache as _invalidate_sources_cache,
)
from services.gallery_lifecycle import (
    mark_trashed,
)
from services.library_helpers import check_write_access as _check_write_access
from services.library_helpers import get_or_404_by_source as _get_or_404_by_source
from services.library_helpers import user_gallery_state as _user_gallery_state
from services.library_serializers import serialize_gallery as _g
from services.settings_store import get_toggle as _get_toggle

_member = require_role("member")
router = APIRouter()


class GalleryPatch(BaseModel):
    favorited: bool | None = None
    rating: int | None = None
    in_reading_list: bool | None = None
    title: str | None = None
    title_jpn: str | None = None
    category: str | None = None


@router.patch("/galleries/{source}/{source_id}")
async def update_gallery(
    source: str,
    source_id: str,
    patch: GalleryPatch,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    _check_write_access(auth, g)
    if patch.favorited is not None:
        if patch.favorited:
            stmt = (
                pg_insert(UserFavorite)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gallery_id,
                )
                .on_conflict_do_nothing()
            )
            await db.execute(stmt)
        else:
            await db.execute(
                sa_delete(UserFavorite).where(
                    UserFavorite.user_id == auth["user_id"],
                    UserFavorite.gallery_id == gallery_id,
                )
            )
    if patch.rating is not None:
        if patch.rating == 0:
            await db.execute(
                sa_delete(UserRating).where(
                    UserRating.user_id == auth["user_id"],
                    UserRating.gallery_id == gallery_id,
                )
            )
        else:
            stmt = (
                pg_insert(UserRating)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gallery_id,
                    rating=patch.rating,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "gallery_id"],
                    set_={"rating": patch.rating, "rated_at": func.now()},
                )
            )
            await db.execute(stmt)
    if patch.in_reading_list is not None:
        if patch.in_reading_list:
            stmt = (
                pg_insert(UserReadingList)
                .values(
                    user_id=auth["user_id"],
                    gallery_id=gallery_id,
                )
                .on_conflict_do_nothing()
            )
            await db.execute(stmt)
        else:
            await db.execute(
                sa_delete(UserReadingList).where(
                    UserReadingList.user_id == auth["user_id"],
                    UserReadingList.gallery_id == gallery_id,
                )
            )
    manual_changes = {
        field_name: ("set", value)
        for field_name, value in {
            "title": patch.title,
            "title_jpn": patch.title_jpn,
            "category": patch.category,
        }.items()
        if value is not None
    }
    if manual_changes:
        from services.workbench_metadata import apply_manual_scalar_changes

        await apply_manual_scalar_changes(
            db,
            [g],
            manual_changes,
            actor_user_id=auth["user_id"],
            operation_id=None,
        )
    await db.commit()
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.GALLERY_UPDATED, actor_user_id=auth["user_id"], resource_type="gallery", resource_id=gallery_id
    )
    # Fetch updated per-user state to return accurate response
    is_fav, my_rating, in_rl = await _user_gallery_state(db, auth["user_id"], gallery_id)
    return _g(g, is_favorited=is_fav, my_rating=my_rating, in_reading_list=in_rl)


@router.delete("/galleries/{source}/{source_id}")
async def delete_gallery(
    source: str,
    source_id: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a gallery by setting deleted_at timestamp.

    The gallery is moved to trash and can be restored or permanently deleted later.
    A GC worker will permanently delete galleries that have been in trash longer
    than the configured retention period.
    """
    g = await _get_or_404_by_source(db, source, source_id, auth)
    _check_write_access(auth, g)

    from db.models import DownloadJob

    active_job = (
        await db.execute(
            select(DownloadJob.id)
            .where(
                DownloadJob.gallery_id == g.id,
                DownloadJob.status.in_(["queued", "running", "paused"]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_job:
        raise HTTPException(
            status_code=409, detail="Cannot delete gallery with active download job. Cancel the download first."
        )

    # Check if trash is enabled
    trash_enabled = await _get_toggle("setting:trash_enabled", True)

    if not trash_enabled:
        # Hard-delete immediately when trash is disabled
        result = await _hard_delete_galleries(db, [g])
        await _invalidate_sources_cache()
        return {"status": "ok", **result}

    mark_trashed([g], reason="user", actor_user_id=auth["user_id"])
    await db.commit()
    await _invalidate_sources_cache()
    from core.events import EventType, emit_safe

    await emit_safe(EventType.GALLERY_DELETED, actor_user_id=auth["user_id"], resource_type="gallery", resource_id=g.id)
    return {"status": "ok", "deleted_files": 0}
