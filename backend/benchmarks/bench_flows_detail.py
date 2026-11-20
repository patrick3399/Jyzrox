"""Benchmark flows 3-5: gallery images, explorer, worker pressure."""

import sys
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# sys.path — ensure backend/ is importable
# ---------------------------------------------------------------------------

_backend_dir = str(Path(__file__).parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# ---------------------------------------------------------------------------
from benchmarks.bench_common import (  # noqa: E402
    BenchResult,
    _run_bench,
)
from db.models import (  # noqa: E402
    Blob,
    Gallery,
    GalleryTag,
    Image,
    Tag,
)

# ---------------------------------------------------------------------------
# Flow 3: Gallery Images
# ---------------------------------------------------------------------------


async def bench_gallery_detail(session: AsyncSession) -> BenchResult:
    """Single gallery lookup by primary key."""
    gid_row = (await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_(None)).limit(1))).first()
    gid = gid_row[0] if gid_row else 1
    stmt = select(Gallery).where(Gallery.id == gid)
    return await _run_bench("gallery_detail", "Gallery Images", session, stmt)


async def bench_gallery_images_page1(session: AsyncSession) -> BenchResult:
    """Images for a single gallery — first page of 40."""
    gid_row = (await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_(None)).limit(1))).first()
    gid = gid_row[0] if gid_row else 1
    stmt = select(Image).where(Image.gallery_id == gid).order_by(Image.page_num).limit(40)
    return await _run_bench("gallery_images_page1", "Gallery Images", session, stmt)


async def bench_gallery_tags(session: AsyncSession) -> BenchResult:
    """Gallery tags for a single gallery (gallery_tags JOIN tags)."""
    gid_row = (await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_(None)).limit(1))).first()
    gid = gid_row[0] if gid_row else 1
    stmt = (
        select(GalleryTag, Tag)
        .join(Tag, GalleryTag.tag_id == Tag.id)
        .where(GalleryTag.gallery_id == gid)
        .order_by(desc(GalleryTag.confidence))
    )
    return await _run_bench("gallery_tags", "Gallery Images", session, stmt)


async def bench_image_browser_cross(session: AsyncSession) -> BenchResult:
    """Cross-gallery image browser — newest images across all galleries, limit 40."""
    stmt = (
        select(Image)
        .join(Gallery, Image.gallery_id == Gallery.id)
        .where(Gallery.deleted_at.is_(None), Gallery.visibility == "public")
        .order_by(desc(Image.added_at), desc(Image.id))
        .limit(40)
    )
    return await _run_bench("image_browser_cross", "Gallery Images", session, stmt)


# ---------------------------------------------------------------------------
# Flow 4: Explorer
# ---------------------------------------------------------------------------


async def bench_explorer_galleries_by_source(session: AsyncSession) -> BenchResult:
    """Explorer: galleries filtered by source='ehentai'."""
    stmt = (
        select(Gallery)
        .where(Gallery.source == "ehentai", Gallery.deleted_at.is_(None))
        .order_by(desc(Gallery.added_at), desc(Gallery.id))
        .limit(40)
    )
    return await _run_bench("explorer_galleries_by_source", "Explorer", session, stmt)


async def bench_explorer_gallery_images(session: AsyncSession) -> BenchResult:
    """Explorer: all images for a specific gallery (no page limit)."""
    gid_row = (await session.execute(select(Gallery.id).where(Gallery.deleted_at.is_(None)).limit(1))).first()
    gid = gid_row[0] if gid_row else 1
    stmt = (
        select(Image.id, Image.page_num, Image.filename, Image.blob_sha256)
        .where(Image.gallery_id == gid)
        .order_by(Image.page_num)
    )
    return await _run_bench("explorer_gallery_images", "Explorer", session, stmt)


# ---------------------------------------------------------------------------
# Flow 5: Worker Pressure
# ---------------------------------------------------------------------------


async def bench_dedup_load_blobs(session: AsyncSession) -> BenchResult:
    """Dedup worker: load sha256 + phash_int for all blobs with a known pHash."""
    stmt = select(Blob.sha256, Blob.phash_int).where(Blob.phash_int.is_not(None)).order_by(Blob.sha256).limit(10_000)
    return await _run_bench("dedup_load_blobs", "Worker Pressure", session, stmt)


# ---------------------------------------------------------------------------
# Summary table printer
