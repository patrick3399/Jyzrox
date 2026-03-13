"""Progressive import: import files and generate thumbnails during download."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from db.models import Blob, Gallery, Image
from services.cas import cas_path, create_library_symlink, store_blob
from worker.constants import _VIDEO_EXTS, logger
from worker.helpers import _sha256, _validate_image_magic
from worker.thumbnail import generate_single_thumbnail


class ProgressiveImporter:
    """Imports files progressively during gallery-dl download."""

    def __init__(self, db_job_id: str | None, user_id: int | None):
        self.db_job_id = db_job_id
        self.user_id = user_id
        self.gallery_id: int | None = None
        self.title: str | None = None
        self.source: str | None = None
        self.source_id: str | None = None
        self._processed: set[str] = set()
        self._page_counter = 0
        self._sem = asyncio.Semaphore(2)
        self._tasks: list[asyncio.Task] = []

    async def ensure_gallery(self, metadata: dict, dest_dir: Path) -> int:
        """Create or update gallery record with download_status='downloading'.

        Uses parse_gallery_dl_import from the plugin's metadata parser.
        Returns gallery_id.
        """
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        import_data = parse_gallery_dl_import(dest_dir, metadata)
        self.title = import_data.title
        self.source = import_data.source
        self.source_id = import_data.source_id

        async with AsyncSessionLocal() as session:
            stmt = (
                pg_insert(Gallery)
                .values(
                    source=import_data.source,
                    source_id=import_data.source_id,
                    title=import_data.title,
                    title_jpn=import_data.title_jpn,
                    category=import_data.category,
                    language=import_data.language,
                    pages=0,
                    posted_at=import_data.posted_at,
                    uploader=import_data.uploader,
                    download_status="downloading",
                    tags_array=import_data.tags,
                    artist_id=import_data.artist_id,
                    created_by_user_id=self.user_id,
                )
                .on_conflict_do_update(
                    index_elements=["source", "source_id"],
                    set_={
                        "title": pg_insert(Gallery).excluded.title,
                        "tags_array": pg_insert(Gallery).excluded.tags_array,
                        "download_status": "downloading",
                        "artist_id": pg_insert(Gallery).excluded.artist_id,
                    },
                )
                .returning(Gallery.id)
            )
            self.gallery_id = (await session.execute(stmt)).scalar_one()

            # Link gallery_id to the DownloadJob
            if self.db_job_id:
                from db.models import DownloadJob
                job = await session.get(DownloadJob, uuid.UUID(self.db_job_id))
                if job:
                    job.gallery_id = self.gallery_id

            await session.commit()

        logger.info("[progressive] gallery created: id=%d title=%s", self.gallery_id, self.title)
        return self.gallery_id

    async def ensure_gallery_from_url(self, url: str, dest_dir: Path) -> int:
        """Fallback: create gallery from URL when no metadata JSON is available."""
        from urllib.parse import urlparse

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from plugins.registry import plugin_registry

        parsed = urlparse(url)
        domain = parsed.netloc.removeprefix("www.")

        # Derive source from domain
        source = "gallery_dl"
        for site in plugin_registry.get_supported_sites():
            if site.domain == domain:
                source = site.source_id
                break

        # Derive source_id from URL path
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        source_id = path_parts[0] if path_parts else dest_dir.name
        title = source_id

        self.title = title
        self.source = source
        self.source_id = source_id

        async with AsyncSessionLocal() as session:
            stmt = (
                pg_insert(Gallery)
                .values(
                    source=source,
                    source_id=source_id,
                    title=title,
                    pages=0,
                    download_status="downloading",
                    created_by_user_id=self.user_id,
                )
                .on_conflict_do_update(
                    index_elements=["source", "source_id"],
                    set_={
                        "download_status": "downloading",
                    },
                )
                .returning(Gallery.id)
            )
            self.gallery_id = (await session.execute(stmt)).scalar_one()

            if self.db_job_id:
                from db.models import DownloadJob
                job = await session.get(DownloadJob, uuid.UUID(self.db_job_id))
                if job:
                    job.gallery_id = self.gallery_id

            await session.commit()

        logger.info("[progressive] gallery created from URL: id=%d title=%s", self.gallery_id, self.title)
        return self.gallery_id

    async def import_file(self, file_path: Path) -> None:
        """Import a single media file with bounded concurrency.

        Page number is assigned here (serial caller) to guarantee deterministic
        ordering regardless of how tasks are scheduled.
        """
        str_path = str(file_path)
        if str_path in self._processed:
            return
        self._processed.add(str_path)

        # Assign page_num serially to guarantee correct ordering
        self._page_counter += 1
        page_num = self._page_counter

        # Prune completed tasks to avoid unbounded growth
        self._tasks = [t for t in self._tasks if not t.done()]

        async def _do_import():
            async with self._sem:
                await self._import_single(file_path, page_num)

        task = asyncio.create_task(_do_import())
        self._tasks.append(task)

    async def _import_single(self, file_path: Path, page_num: int) -> None:
        """Import one file: sha256 -> store_blob -> image record -> symlink -> thumbnail."""
        if not file_path.exists():
            return

        # Validate image magic bytes (skip check for videos)
        if file_path.suffix.lower() not in _VIDEO_EXTS:
            if not _validate_image_magic(file_path):
                logger.warning("[progressive] invalid magic bytes, skipping: %s", file_path.name)
                return

        try:
            sha256 = await asyncio.to_thread(_sha256, file_path)

            async with AsyncSessionLocal() as session:
                blob = await store_blob(file_path, sha256, session)
                await session.flush()

                img_stmt = (
                    pg_insert(Image)
                    .values(
                        gallery_id=self.gallery_id,
                        page_num=page_num,
                        filename=file_path.name,
                        blob_sha256=sha256,
                        added_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing()
                )
                await session.execute(img_stmt)

                # Create library symlink before closing session (need blob data)
                await create_library_symlink(self.gallery_id, file_path.name, blob)

                # Generate thumbnail within the same session so blob modifications
                # (width, height, phash, thumbhash) are tracked and committed
                src = cas_path(blob.sha256, blob.extension)
                if not src.exists() and blob.storage == "external" and blob.external_path:
                    src = Path(blob.external_path)

                await generate_single_thumbnail(blob, src, session)
                await session.commit()

            logger.info("[progressive] imported: %s (page %d)", file_path.name, page_num)

        except Exception as exc:
            logger.warning("[progressive] failed to import %s: %s", file_path.name, exc)

    async def finalize(self, dest_dir: Path, *, partial: bool = False) -> int | None:
        """Wait for pending tasks, update gallery pages + status, clean up temp dir."""
        if self._tasks:
            results = await asyncio.gather(*self._tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("[progressive] task error during finalize: %s", r)
            self._tasks.clear()

        if not self.gallery_id:
            return None

        async with AsyncSessionLocal() as session:
            from sqlalchemy import func
            gallery = await session.get(Gallery, self.gallery_id)
            if gallery:
                count = (await session.execute(
                    select(func.count()).where(Image.gallery_id == self.gallery_id)
                )).scalar_one()
                gallery.pages = count
                gallery.download_status = "partial" if partial else "complete"
                await session.commit()

        try:
            import shutil
            if dest_dir.exists():
                shutil.rmtree(str(dest_dir), ignore_errors=True)
        except Exception as exc:
            logger.warning("[progressive] failed to remove temp dir %s: %s", dest_dir, exc)

        logger.info("[progressive] finalized: gallery_id=%d pages=%d", self.gallery_id, self._page_counter)

        from core.config import settings
        if settings.tag_model_enabled:
            from core.redis_client import get_redis
            r = get_redis()
            await r.enqueue_job("tag_job", self.gallery_id)

        return self.gallery_id

    async def abort(self) -> None:
        """Cancel pending tasks and set gallery status to 'partial'. Called on failure/cancellation."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        if not self.gallery_id:
            return

        async with AsyncSessionLocal() as session:
            from sqlalchemy import func
            gallery = await session.get(Gallery, self.gallery_id)
            if gallery:
                count = (await session.execute(
                    select(func.count()).where(Image.gallery_id == self.gallery_id)
                )).scalar_one()
                gallery.pages = count
                gallery.download_status = "partial" if count > 0 else "downloading"
                await session.commit()
