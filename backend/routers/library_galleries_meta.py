"""Library split from routers/library.py (library_galleries_meta)."""

import json

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter, require_auth
from core.database import get_db
from core.redis_client import get_redis
from db.models import (
    Gallery,
)
from services.site_catalog import get_site_config as _get_gdl_site_config

router = APIRouter()


def _source_label(src: str) -> str:
    """Display label for a non-local source (site name when known, else the raw id)."""
    cfg = _get_gdl_site_config(src)
    return cfg.name if cfg.source_id == src else src


_SOURCES_CACHE_KEY = "library:sources"


_SOURCES_CACHE_TTL = 300  # 5 minutes


@router.get("/galleries/sources")
async def list_gallery_sources(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return distinct source values from the galleries table.

    Cached in Redis for 5 minutes to avoid repeated DB hits.
    """
    r = get_redis()
    cached = await r.get(_SOURCES_CACHE_KEY)
    if cached is not None:
        return json.loads(cached)

    rows = (await db.execute(select(Gallery.source).where(Gallery.source.is_not(None)).distinct())).scalars().all()

    # Build source list with import_mode variants for 'local'
    sources: list[dict] = []
    for src in sorted(rows):
        if src == "local":
            # Check which import_modes exist
            modes = (
                (
                    await db.execute(
                        select(Gallery.import_mode)
                        .where(
                            Gallery.source == "local",
                            Gallery.import_mode.is_not(None),
                        )
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
            for mode in sorted(mode for mode in modes if mode is not None):
                sources.append({"value": f"local:{mode}", "label": f"local:{mode}"})
            if not modes:
                sources.append({"value": "local", "label": "local"})
        else:
            sources.append({"value": src, "label": _source_label(src)})

    await r.set(_SOURCES_CACHE_KEY, json.dumps(sources), ex=_SOURCES_CACHE_TTL)
    return sources


@router.get("/galleries/categories")
async def list_gallery_categories(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return distinct non-empty category values from the galleries table."""
    result = await db.execute(
        select(Gallery.category)
        .where(Gallery.category.isnot(None), Gallery.category != "")
        .distinct()
        .order_by(Gallery.category)
    )
    return {"categories": [r[0] for r in result.all()]}


@router.get("/galleries/facets")
async def get_gallery_facets(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Per-user counts for the Library Source / Category multi-select filters.

    Both queries apply gallery_access_filter (also excludes soft-deleted), so a
    viewer never sees counts for galleries they cannot open. Not cached: the
    result differs per user and the GROUP BYs are cheap.
    """
    access = gallery_access_filter(auth)
    count_col = func.count(Gallery.id)

    source_rows = (
        await db.execute(
            select(Gallery.source, Gallery.import_mode, count_col)
            .where(access, Gallery.source.is_not(None))
            .group_by(Gallery.source, Gallery.import_mode)
        )
    ).all()

    merged: dict[str, dict] = {}
    for src, mode, cnt in source_rows:
        if src == "local":
            value = f"local:{mode}" if mode else "local"
            label = value
        else:
            value, label = src, _source_label(src)
        entry = merged.setdefault(value, {"value": value, "label": label, "count": 0})
        entry["count"] += cnt
    sources = sorted(merged.values(), key=lambda e: (-e["count"], e["label"]))

    category_rows = (
        await db.execute(
            select(Gallery.category, count_col)
            .where(access, Gallery.category.is_not(None), Gallery.category != "")
            .group_by(Gallery.category)
        )
    ).all()
    categories = sorted(
        ({"name": name, "count": cnt} for name, cnt in category_rows),
        key=lambda e: (-e["count"], e["name"]),
    )

    uncategorized = (
        await db.execute(select(count_col).where(access, or_(Gallery.category.is_(None), Gallery.category == "")))
    ).scalar_one()

    return {"sources": sources, "categories": categories, "uncategorized": uncategorized}
