"""Pixiv author collection synchronization.

An author URL is a collection endpoint: all artworks are imported into one
gallery while source-work rows preserve chapter boundaries and ordering.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.config import settings
from core.database import AsyncSessionLocal
from core.events import EventType, emit_safe
from db.models import DownloadJob, Gallery, GallerySourceItem, Image, ReadProgress, Subscription
from plugins.models import GalleryImportData
from services.credential import get_credential
from services.pixiv_client import PixivClient
from services.pixiv_downloader import download_pixiv_illust
from worker.helpers import _set_job_progress, _set_job_status
from worker.progressive import ProgressiveImporter

_PIXIV_PAGE_RE = re.compile(r"^pixiv:(\d+):p(\d+)$")


def _published_at(illust: dict) -> datetime | None:
    raw = illust.get("create_date")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _work_metadata(illust: dict) -> dict:
    return {
        "type": illust.get("type"),
        "tags": illust.get("tags") or [],
        "total_bookmarks": illust.get("total_bookmarks", 0),
        "total_view": illust.get("total_view", 0),
    }


async def _discover(client: PixivClient, user_id: int, *, stop_at: str | None) -> tuple[list[dict], bool]:
    """Return newest-first works and whether the entire catalogue was traversed."""
    works: list[dict] = []
    offset = 0
    while True:
        # Omitting Pixiv's type filter returns both illustrations and manga;
        # novels use a separate API and intentionally remain out of scope.
        data = await client.user_illusts(user_id, type=None, offset=offset)
        page = data.get("illusts") or []
        if not page:
            return works, True
        for illust in page:
            illust_id = str(illust.get("id") or "")
            if stop_at and illust_id == stop_at:
                return works, False
            if illust_id:
                works.append(illust)
        next_offset = data.get("next_offset")
        if next_offset is None:
            return works, True
        offset = int(next_offset)
        await asyncio.sleep(0)


async def _reorder_author_gallery(gallery_id: int) -> None:
    """Apply published-desc/work-id-desc/page-asc ordering and repair progress."""
    async with AsyncSessionLocal() as session:
        source_items = (
            (await session.execute(select(GallerySourceItem).where(GallerySourceItem.gallery_id == gallery_id)))
            .scalars()
            .all()
        )

        def item_key(item: GallerySourceItem):
            try:
                illust_id = int(item.source_item_id.split(":", 1)[1])
            except IndexError, ValueError:
                illust_id = 0
            published = item.published_at.timestamp() if item.published_at else 0
            return (-published, -illust_id, item.id)

        for position, item in enumerate(sorted(source_items, key=item_key), start=1):
            item.source_position = position

        rows = (
            await session.execute(
                select(Image, GallerySourceItem)
                .join(GallerySourceItem, GallerySourceItem.id == Image.source_item_row_id)
                .where(Image.gallery_id == gallery_id, Image.visibility.in_(("active", "user_hidden")))
            )
        ).all()

        def key(row):
            image, item = row
            match = _PIXIV_PAGE_RE.match(image.source_item_id or "")
            illust_id = int(match.group(1)) if match else 0
            page = int(match.group(2)) if match else (image.source_position or image.page_num)
            published = item.published_at.timestamp() if item.published_at else 0
            return (-published, -illust_id, page, image.id)

        ordered_active = [row[0] for row in sorted((r for r in rows if r[0].visibility == "active"), key=key)]
        anchor_rows = (
            (
                await session.execute(
                    select(ReadProgress).where(
                        ReadProgress.gallery_id == gallery_id,
                        ReadProgress.last_image_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        anchors = {progress.last_image_id: progress for progress in anchor_rows}

        for image in ordered_active:
            image.page_num = -int(image.id)
        await session.flush()
        for position, image in enumerate(ordered_active, start=1):
            image.page_num = position
            image.source_position = position
            if image.id in anchors:
                anchors[image.id].last_page = position

        active_keys = [(key(row), row[0]) for row in rows if row[0].visibility == "active"]
        for row in (r for r in rows if r[0].visibility == "user_hidden"):
            row[0].source_position = 1 + sum(1 for active_key, _ in active_keys if active_key < key(row))

        gallery = await session.get(Gallery, gallery_id)
        if gallery:
            gallery.pages = len(ordered_active)
            gallery.download_status = "complete"
            gallery.metadata_updated_at = func.now()
        await session.commit()


async def pixiv_collection_job(
    ctx: dict,
    user_id: int,
    owner_user_id: int,
    db_job_id: str,
    full_reconcile: bool = False,
    subscription_id: int | None = None,
) -> dict:
    """Create or incrementally synchronize one Pixiv author gallery."""
    job_uuid = uuid.UUID(db_job_id)
    await _set_job_status(db_job_id, "running")
    credential = await get_credential("pixiv")
    token = credential if isinstance(credential, str) else (credential or {}).get("refresh_token", "")
    if not token:
        await _set_job_status(db_job_id, "failed", "Pixiv credentials not configured")
        return {"status": "failed", "error": "Pixiv credentials not configured"}

    redis = ctx["redis"]
    lock_key = f"pixiv:collection:lock:{owner_user_id}:{user_id}"
    if not await redis.set(lock_key, db_job_id, nx=True, ex=settings.download_job_timeout):
        await _set_job_status(db_job_id, "failed", "Author collection sync already active")
        return {"status": "failed", "error": "sync already active"}

    source_url = f"https://www.pixiv.net/users/{user_id}"
    target_dir = Path(settings.data_gallery_path) / "pixiv" / f"user_{user_id}"
    importer = ProgressiveImporter(db_job_id, owner_user_id)
    importer.source_url = source_url
    seen_ids: set[str] = set()
    completed = 0
    try:
        async with PixivClient(token) as client:
            profile = await client.user_detail(user_id)
            async with AsyncSessionLocal() as session:
                sub = await session.get(Subscription, subscription_id) if subscription_id else None
                stop_at = None if full_reconcile or not sub else sub.last_item_id
                if not full_reconcile and not stop_at:
                    existing_gallery_id = (
                        await session.execute(
                            select(Gallery.id).where(
                                Gallery.source == "pixiv",
                                Gallery.source_id == f"user:{user_id}",
                                Gallery.created_by_user_id == owner_user_id,
                                Gallery.deleted_at.is_(None),
                            )
                        )
                    ).scalar_one_or_none()
                    if existing_gallery_id:
                        latest_item = (
                            await session.execute(
                                select(GallerySourceItem.source_item_id)
                                .where(GallerySourceItem.gallery_id == existing_gallery_id)
                                .order_by(GallerySourceItem.source_position.asc())
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        if latest_item and latest_item.startswith("pixiv:"):
                            stop_at = latest_item.split(":", 1)[1]
            works, exhaustive = await _discover(client, user_id, stop_at=stop_at)
            if full_reconcile and not exhaustive:
                raise RuntimeError("Full Pixiv catalogue traversal did not complete")

        title = profile.get("name") or f"Pixiv user {user_id}"
        await importer.ensure_gallery_from_import_data(
            GalleryImportData(
                source="pixiv",
                source_id=f"user:{user_id}",
                title=title,
                category="pixiv",
                uploader=title,
                artist_id=f"pixiv:{user_id}",
            )
        )
        if importer.skipped_trashed or not importer.gallery_id:
            await _set_job_status(db_job_id, "cancelled", "Author gallery is in trash")
            return {"status": "cancelled"}
        gallery_id = importer.gallery_id

        for index, illust in enumerate(works):
            if await redis.get(f"download:cancel:{db_job_id}") is not None:
                await importer.finalize(target_dir, partial=True)
                await _set_job_status(db_job_id, "cancelled")
                return {"status": "cancelled", "completed": completed}
            while await redis.get(f"download:pause:{db_job_id}") is not None:
                await asyncio.sleep(0.5)

            illust_id = int(illust["id"])
            source_item_id = f"pixiv:{illust_id}"
            seen_ids.add(source_item_id)
            now = datetime.now(UTC)
            async with AsyncSessionLocal() as session:
                stmt = (
                    pg_insert(GallerySourceItem)
                    .values(
                        gallery_id=gallery_id,
                        source_item_id=source_item_id,
                        source_item_url=f"https://www.pixiv.net/artworks/{illust_id}",
                        title=illust.get("title") or str(illust_id),
                        published_at=_published_at(illust),
                        page_count=int(illust.get("page_count") or 1),
                        source_position=index + 1,
                        source_seen_at=now,
                        status="active",
                        metadata_json=_work_metadata(illust),
                    )
                    .on_conflict_do_update(
                        constraint="uq_gallery_source_item",
                        set_={
                            "title": illust.get("title") or str(illust_id),
                            "published_at": _published_at(illust),
                            "page_count": int(illust.get("page_count") or 1),
                            "source_position": index + 1,
                            "source_seen_at": now,
                            "status": "active",
                            "metadata_json": _work_metadata(illust),
                        },
                    )
                )
                await session.execute(stmt)
                await session.commit()

            result = await download_pixiv_illust(
                illust_id=illust_id,
                refresh_token=token,
                output_dir=target_dir / str(illust_id),
                on_file=importer.import_file,
                filename_prefix=str(illust_id),
            )
            if result["status"] != "done":
                raise RuntimeError(result.get("error") or f"Failed to download artwork {illust_id}")
            completed += 1
            await _set_job_progress(
                db_job_id,
                {
                    "downloaded": completed,
                    "total": len(works),
                    "gallery_id": gallery_id,
                    "status_text": f"Syncing {title} ({completed}/{len(works)})",
                },
            )

        await importer.finalize(target_dir)
        async with AsyncSessionLocal() as session:
            items = (
                (await session.execute(select(GallerySourceItem).where(GallerySourceItem.gallery_id == gallery_id)))
                .scalars()
                .all()
            )
            item_ids = {item.source_item_id: item.id for item in items}
            for item_key, row_id in item_ids.items():
                await session.execute(
                    update(Image)
                    .where(Image.gallery_id == gallery_id, Image.source_item_id.like(f"{item_key}:p%"))
                    .values(source_item_row_id=row_id)
                )
            if full_reconcile and exhaustive:
                await session.execute(
                    update(GallerySourceItem)
                    .where(
                        GallerySourceItem.gallery_id == gallery_id,
                        GallerySourceItem.source_item_id.not_in(seen_ids),
                    )
                    .values(status="source_missing")
                )
            job = await session.get(DownloadJob, job_uuid)
            if job:
                job.gallery_id = gallery_id
            if subscription_id:
                sub = await session.get(Subscription, subscription_id)
                if sub:
                    sub.source_id = str(user_id)
                    if not sub.name or sub.name == f"Pixiv user {user_id}":
                        sub.name = title
                    sub.last_checked_at = datetime.now(UTC)
                    sub.last_success_at = datetime.now(UTC)
                    sub.last_status = "up_to_date" if not works else "done"
                    sub.last_error = None
                    if works:
                        sub.last_item_id = str(works[0]["id"])
            await session.commit()

        await _reorder_author_gallery(gallery_id)
        await _set_job_status(db_job_id, "done")
        await emit_safe(
            EventType.DOWNLOAD_COMPLETED,
            actor_user_id=owner_user_id,
            resource_type="pixiv_author_collection",
            resource_id=gallery_id,
            pixiv_user_id=user_id,
            completed=completed,
            full_reconcile=full_reconcile,
        )
        return {"status": "done", "gallery_id": gallery_id, "completed": completed}
    except Exception as exc:
        await importer.finalize(target_dir, partial=True) if importer.gallery_id else importer.cleanup()
        await _set_job_status(db_job_id, "failed", str(exc))
        await emit_safe(
            EventType.DOWNLOAD_FAILED,
            actor_user_id=owner_user_id,
            resource_type="pixiv_author_collection",
            resource_id=user_id,
            error=str(exc),
        )
        if subscription_id:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Subscription)
                    .where(Subscription.id == subscription_id)
                    .values(last_status="failed", last_error=str(exc)[:500])
                )
                await session.commit()
        return {"status": "failed", "error": str(exc)}
    finally:
        if await redis.get(lock_key) in (db_job_id, db_job_id.encode()):
            await redis.delete(lock_key)
