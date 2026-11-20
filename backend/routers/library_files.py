"""Library split from routers/library.py (library_files)."""

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter, require_auth
from core.database import get_db
from core.gallery_helpers import (
    get_favorite_set,
    get_rating_map,
)
from core.utils import escape_like
from db.models import (
    Blob,
    Gallery,
    Image,
)
from services.cas import (
    existing_base_thumbs,
    image_file_url,
    library_dir,
)
from services.library_helpers import get_or_404_by_source as _get_or_404_by_source
from services.library_serializers import media_type as _media_type
from services.library_serializers import thumb_fields as _thumb_fields
from services.library_sidecar import SIDECAR_FILENAME

# Backward-compat aliases — functions now live in core.gallery_helpers
_get_favorite_set = get_favorite_set
_get_rating_map = get_rating_map
router = APIRouter()


@router.get("/files/source_stats")
async def source_stats(
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Per-source aggregate stats for the explorer root view.

    The root view must list every source in the library; deriving it from one
    page of /files hides sources whose galleries are all older than the newest
    page (and reports per-source stats computed over that page only).
    local galleries are grouped per import_mode so the frontend can keep its
    link/copy split.
    """
    stmt = (
        select(
            Gallery.source,
            Gallery.import_mode,
            func.count(func.distinct(Gallery.id)).label("gallery_count"),
            func.count(Image.id).label("file_count"),
            func.coalesce(func.sum(func.coalesce(Blob.file_size, Image.source_size)), 0).label("disk_size"),
        )
        .outerjoin(Image, Image.gallery_id == Gallery.id)
        .outerjoin(Blob, Blob.sha256 == Image.blob_sha256)
        .where(gallery_access_filter(auth))
        .group_by(Gallery.source, Gallery.import_mode)
    )
    rows = (await db.execute(stmt)).all()
    return {
        "stats": [
            {
                "source": row.source,
                "import_mode": row.import_mode,
                "gallery_count": row.gallery_count,
                "file_count": row.file_count,
                "disk_size": row.disk_size,
            }
            for row in rows
        ]
    }


@router.get("/files")
async def list_files(
    q: str = Query(default=""),
    source: str | None = Query(default=None),
    import_mode: str | None = Query(default=None),
    page: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List library galleries with image counts and size from DB metadata."""
    filters = [gallery_access_filter(auth)]
    if q:
        filters.append(Gallery.title.ilike(f"%{escape_like(q)}%", escape="\\"))
    if source:
        filters.append(Gallery.source == source)
    if import_mode:
        filters.append(Gallery.import_mode == import_mode)

    total = (await db.execute(select(func.count()).select_from(Gallery).where(*filters))).scalar_one()

    image_counts = func.count(Image.id).label("file_count")
    disk_size = func.coalesce(func.sum(func.coalesce(Blob.file_size, Image.source_size)), 0).label("disk_size")
    stmt = (
        select(Gallery, image_counts, disk_size)
        .outerjoin(Image, Image.gallery_id == Gallery.id)
        .outerjoin(Blob, Blob.sha256 == Image.blob_sha256)
        .where(*filters)
        .group_by(Gallery.id)
        .order_by(Gallery.id.desc())
        .offset(page * limit)
        .limit(limit)
    )

    rows = (await db.execute(stmt)).all()
    paged_ids = [g.id for g, _, _ in rows]
    fav_set = await _get_favorite_set(db, auth["user_id"], paged_ids)
    rating_map = await _get_rating_map(db, auth["user_id"], paged_ids)

    result = []
    for g, file_count, total_size in rows:
        result.append(
            {
                "gallery_id": g.id,
                "source_id": g.source_id,
                "title": g.title,
                "category": g.category,
                "file_count": file_count,
                "rating": g.rating,
                "favorited": False,
                "is_favorited": g.id in fav_set,
                "my_rating": rating_map.get(g.id, 0),
                "source": g.source,
                "import_mode": g.import_mode,
                "artist_id": g.artist_id,
                "uploader": g.uploader,
                "library_path": g.library_path,
                "source_path": g.source_path,
                "disk_size": total_size,
            }
        )

    return {"directories": result, "total": total, "page": page}


@router.get("/files/{source}/{source_id}")
async def list_gallery_files(
    source: str,
    source_id: str,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List all files inside a gallery's library directory with DB metadata."""
    import asyncio
    import os

    g = await _get_or_404_by_source(db, source, source_id, auth)
    gallery_id = g.id
    gdir = library_dir(g.source, g.source_id)

    def _scan_files() -> list[dict]:
        """Scan the gallery directory and return raw file info."""
        entries = []
        try:
            for entry in os.scandir(gdir):
                if entry.name == SIDECAR_FILENAME:
                    # Disaster-recovery metadata sidecar, not gallery content
                    continue
                if not entry.is_file(follow_symlinks=False) and not entry.is_symlink():
                    continue
                path = Path(entry.path)
                is_symlink = path.is_symlink()
                is_broken = is_symlink and not path.exists()
                symlink_target: str | None = None
                if is_symlink:
                    try:
                        symlink_target = os.readlink(path)
                    except OSError:
                        pass
                file_size: int | None = None
                if not is_broken:
                    try:
                        file_size = entry.stat(follow_symlinks=True).st_size
                    except OSError:
                        pass
                entries.append(
                    {
                        "filename": entry.name,
                        "file_size": file_size,
                        "is_symlink": is_symlink,
                        "is_broken": is_broken,
                        "symlink_target": symlink_target,
                    }
                )
        except OSError:
            pass
        return entries

    raw_files = await asyncio.to_thread(_scan_files)

    # Cross-reference with DB Image records by filename
    filenames = [f["filename"] for f in raw_files]
    img_map: dict[str, Image] = {}
    if filenames:
        img_stmt = (
            select(Image)
            .where(Image.gallery_id == gallery_id, Image.filename.in_(filenames))
            .options(selectinload(Image.blob))
        )
        db_images = (await db.execute(img_stmt)).scalars().all()
        img_map = {img.filename: img for img in db_images if img.filename is not None}
    thumbs = await existing_base_thumbs(img.blob_sha256 for img in img_map.values())

    files = []
    for f in sorted(raw_files, key=lambda x: x["filename"]):
        img = img_map.get(f["filename"])
        blob = img.blob if img else None
        files.append(
            {
                "filename": f["filename"],
                "page_num": img.page_num if img else None,
                "width": blob.width if blob else None,
                "height": blob.height if blob else None,
                "file_size": f["file_size"],
                "media_type": _media_type(img) if img else "image",
                **_thumb_fields(blob, thumbs),
                "file_path": image_file_url(blob, img.external_path if img else None),
                "is_symlink": f["is_symlink"],
                "is_broken": f["is_broken"],
                "symlink_target": f["symlink_target"],
            }
        )

    return {
        "gallery_id": gallery_id,
        "source": g.source,
        "source_id": g.source_id,
        "title": g.title,
        "category": g.category,
        "files": files,
        "total_files": len(files),
    }
