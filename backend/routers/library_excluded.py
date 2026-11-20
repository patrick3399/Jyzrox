"""Library split from routers/library.py (library_excluded)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import has_gallery_write_access, require_auth, require_role
from core.database import get_db
from db.models import (
    ExcludedBlob,
    Image,
)
from services.cas import (
    decrement_ref_count,
)
from services.library_helpers import check_write_access as _check_write_access
from services.library_helpers import get_or_404_by_source as _get_or_404_by_source
from services.library_helpers import single_cover_thumb as _single_cover_thumb
from services.library_helpers import user_gallery_state as _user_gallery_state
from services.library_serializers import serialize_gallery as _g

_member = require_role("member")
router = APIRouter()


@router.get("/galleries/{source}/{source_id}/excluded")
async def list_excluded_blobs(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List excluded blob hashes for a gallery."""

    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    result = await db.execute(
        select(ExcludedBlob).where(ExcludedBlob.gallery_id == gallery_id).order_by(ExcludedBlob.excluded_at.desc())
    )
    blobs = result.scalars().all()
    return {
        "gallery_id": gallery_id,
        "excluded": [
            {"blob_sha256": b.blob_sha256, "excluded_at": b.excluded_at.isoformat() if b.excluded_at else None}
            for b in blobs
        ],
    }


@router.delete("/galleries/{source}/{source_id}/excluded/{sha256}")
async def restore_excluded_blob(
    source: str,
    source_id: str,
    sha256: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Remove a blob from the exclusion list (un-exclude)."""
    gallery = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = gallery.id
    _check_write_access(auth, gallery)

    result = await db.execute(
        select(ExcludedBlob).where(
            ExcludedBlob.gallery_id == gallery_id,
            ExcludedBlob.blob_sha256 == sha256,
        )
    )
    blob = result.scalar_one_or_none()
    if not blob:
        raise HTTPException(status_code=404, detail="Excluded blob not found")
    await db.delete(blob)
    # A link page whose hash was excluded keeps its row as visibility='excluded'
    # so the next folder sync does not register the file again. Dropping the
    # exclusion must drop that row too, otherwise the file stays hidden forever.
    excluded_rows = (
        (
            await db.execute(
                select(Image.id).where(
                    Image.gallery_id == gallery_id,
                    Image.blob_sha256 == sha256,
                    Image.visibility == "excluded",
                )
            )
        )
        .scalars()
        .all()
    )
    if excluded_rows:
        await db.execute(sa_delete(Image).where(Image.id.in_(excluded_rows)))
        await decrement_ref_count(sha256, db, amount=len(excluded_rows))
    await db.commit()
    return {"status": "ok"}


@router.post("/galleries/{source}/{source_id}/check-update")
async def check_gallery_update(
    source: str,
    source_id: str,
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    """Auto-check and update gallery metadata from source.

    Applying source metadata rewrites title/tags and records change history, so
    this is a mutation: visibility alone is not enough (read-only collaborators
    can see the gallery), the caller needs gallery write access.
    """
    g = await _get_or_404_by_source(db, source, source_id, auth)
    if not await has_gallery_write_access(db, g.id, g.created_by_user_id, auth):
        raise HTTPException(status_code=403, detail="Gallery write access is required")

    from plugins.registry import plugin_registry

    refresher = plugin_registry.get_refresher(source)
    if refresher is None:
        return {"status": "skipped", "reason": "unsupported_source"}

    result = await refresher.fetch_remote_metadata(g.source_id, g.source_url)

    if result.status == "expunged":
        g.metadata_updated_at = func.now()
        await db.commit()
        await db.refresh(g)
        return {"status": "expunged"}
    if result.status in ("skipped", "error"):
        return {"status": result.status, "reason": result.reason}

    old_pages = g.pages

    from services.workbench_metadata import apply_source_scalar_metadata, apply_source_tags

    changed_fields, pending_source_changes = await apply_source_scalar_metadata(db, g, result.scalar_values)
    if result.tags is not None and await apply_source_tags(db, g, result.tags):
        changed_fields.append("tags")

    pages_diff = {"old": old_pages, "new": g.pages} if "pages" in changed_fields else None

    g.metadata_updated_at = func.now()
    await db.commit()
    await db.refresh(g)

    if not changed_fields and not pending_source_changes:
        return {"status": "unchanged"}
    if not changed_fields:
        return {"status": "source_diff", "pending_source_changes": pending_source_changes}
    return await _build_updated_response(
        g, db, auth, changed_fields, pages_diff, pending_source_changes=pending_source_changes
    )


async def _build_updated_response(
    g,
    db: AsyncSession,
    auth: dict,
    changed_fields: list,
    pages_diff: dict | None,
    *,
    pending_source_changes: dict | None = None,
) -> dict:
    cover_thumb = await _single_cover_thumb(db, g.id, g.source or "")
    is_fav, my_rating, in_rl = await _user_gallery_state(db, auth["user_id"], g.id)
    return {
        "status": "updated",
        "gallery": _g(g, cover_thumb, is_fav, my_rating, in_reading_list=in_rl),
        "changed_fields": changed_fields,
        "pages_diff": pages_diff,
        "pending_source_changes": pending_source_changes or {},
    }
