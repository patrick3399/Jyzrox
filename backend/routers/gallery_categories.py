"""Gallery category registry (readable by everyone, managed by admins)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth, require_role
from core.database import get_db
from core.local_category_plan import normalize_category
from db.models import Gallery, GalleryCategory, GalleryMetadataFieldState, LibraryPath
from services.gallery_categories import PALETTE, RESERVED_NAMES, load_category_map, resolve_with_map

router = APIRouter(tags=["gallery-categories"])
logger = logging.getLogger(__name__)

_admin = require_role("admin")

_BACKFILL_CHUNK = 500


class CategoryCreate(BaseModel):
    name: str
    color: str = "gray"


class CategoryColorPatch(BaseModel):
    color: str


class BackfillRequest(BaseModel):
    dry_run: bool = True


def _item(row: GalleryCategory, usage: dict[str, int]) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "color": row.color,
        "sort_order": row.sort_order,
        "is_builtin": bool(row.is_builtin),
        "gallery_count": usage.get(row.name.lower(), 0),
    }


async def _usage_counts(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(
            select(func.lower(Gallery.category), func.count())
            .where(Gallery.deleted_at.is_(None), Gallery.category.isnot(None), Gallery.category != "")
            .group_by(func.lower(Gallery.category))
        )
    ).all()
    return {key: count for key, count in rows}


def _validate_color(color: str) -> None:
    if color not in PALETTE:
        raise HTTPException(status_code=422, detail="Unknown colour")


@router.get("/")
async def list_categories(_: dict = Depends(require_auth), db: AsyncSession = Depends(get_db)):
    rows = (
        (
            await db.execute(
                select(GalleryCategory).order_by(
                    GalleryCategory.is_builtin.desc(), GalleryCategory.sort_order, GalleryCategory.id
                )
            )
        )
        .scalars()
        .all()
    )
    usage = await _usage_counts(db)
    return {"categories": [_item(r, usage) for r in rows], "palette": list(PALETTE)}


@router.post("/", status_code=201)
async def create_category(body: CategoryCreate, _: dict = Depends(_admin), db: AsyncSession = Depends(get_db)):
    name = normalize_category(body.name)
    if name is None or name.lower() in RESERVED_NAMES:
        raise HTTPException(status_code=422, detail="Invalid category name")
    _validate_color(body.color)
    if name.lower() in await load_category_map(db):
        raise HTTPException(status_code=409, detail="Category already exists")

    next_order = (await db.execute(select(func.coalesce(func.max(GalleryCategory.sort_order), 0)))).scalar_one() + 1
    row = GalleryCategory(name=name, color=body.color, sort_order=next_order, is_builtin=False)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Category already exists") from None
    item = _item(row, {})
    await db.commit()
    return item


@router.patch("/{category_id}")
async def update_category_color(
    category_id: int,
    body: CategoryColorPatch,
    _: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(GalleryCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")
    if row.is_builtin:
        raise HTTPException(status_code=403, detail="Built-in categories cannot be modified")
    _validate_color(body.color)
    row.color = body.color
    usage = await _usage_counts(db)
    item = _item(row, usage)
    await db.commit()
    return item


@router.delete("/{category_id}")
async def delete_category(category_id: int, _: dict = Depends(_admin), db: AsyncSession = Depends(get_db)):
    row = await db.get(GalleryCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")
    if row.is_builtin:
        raise HTTPException(status_code=403, detail="Built-in categories cannot be deleted")

    name = row.name
    # Library directories and source_id keep the old category segment (ADR 0013);
    # only the database value is cleared. Trashed galleries are cleared too so a
    # restore cannot resurrect a category that no longer exists.
    cleared = await db.execute(
        update(Gallery)
        .where(func.lower(Gallery.category) == name.lower())
        .values(category=None)
        .execution_options(synchronize_session=False)
    )
    await db.delete(row)
    await db.commit()
    logger.info("[categories] deleted %r, cleared %d galleries", name, cleared.rowcount)
    return {"deleted": name, "galleries_cleared": cleared.rowcount}


async def _backfill_candidates(db: AsyncSession) -> list[tuple[int, str]]:
    """Local galleries with no category whose first source_id segment names a registered category."""
    libraries = (await db.execute(select(LibraryPath.path, LibraryPath.pattern))).all()
    roots = [path for path, pattern in libraries if (pattern or "").startswith("{category}/")]
    if not roots:
        return []
    manually_set = exists().where(
        and_(
            GalleryMetadataFieldState.gallery_id == Gallery.id,
            GalleryMetadataFieldState.field_name == "category",
            GalleryMetadataFieldState.origin == "manual",
        )
    )
    rows = (
        await db.execute(
            select(Gallery.id, Gallery.source_id).where(
                Gallery.source == "local",
                Gallery.deleted_at.is_(None),
                or_(Gallery.category.is_(None), Gallery.category == ""),
                Gallery.library_path.in_(roots),
                ~manually_set,
            )
        )
    ).all()
    category_map = await load_category_map(db)
    matched: list[tuple[int, str]] = []
    for gallery_id, source_id in rows:
        canonical = resolve_with_map(source_id.split("/", 1)[0], category_map)
        if canonical is not None:
            matched.append((gallery_id, canonical))
    return matched


@router.post("/backfill")
async def backfill_from_folders(
    body: BackfillRequest | None = None,
    _: dict = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    """Apply registered categories to uncategorized local galleries from their folder name.

    Discovery only writes a category on first import (ADR 0013), so a category
    registered later never reaches galleries discovered earlier. This is the
    explicit operator action that closes that gap. It never touches a gallery
    that already has a category or whose category a user set/cleared by hand.
    """
    dry_run = True if body is None else body.dry_run
    matched = await _backfill_candidates(db)
    applied = 0
    if not dry_run and matched:
        by_name: dict[str, list[int]] = {}
        for gallery_id, name in matched:
            by_name.setdefault(name, []).append(gallery_id)
        for name, ids in by_name.items():
            for start in range(0, len(ids), _BACKFILL_CHUNK):
                chunk = ids[start : start + _BACKFILL_CHUNK]
                result = await db.execute(
                    update(Gallery)
                    .where(Gallery.id.in_(chunk), or_(Gallery.category.is_(None), Gallery.category == ""))
                    .values(category=name)
                    .execution_options(synchronize_session=False)
                )
                applied += result.rowcount
        await db.commit()
    return {"dry_run": dry_run, "matched": len(matched), "applied": applied}
