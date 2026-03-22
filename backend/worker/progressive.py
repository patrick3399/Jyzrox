"""Progressive import: import files and generate thumbnails during download."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

from core.database import AsyncSessionLocal
from db.models import Blob, ExcludedBlob, Gallery, Image
from plugins.models import GalleryImportData
from services.cas import cas_path, create_library_symlink, decrement_ref_count, library_dir, store_blob, thumb_dir
from worker.constants import _VIDEO_EXTS, logger
from worker.helpers import _sha256, _validate_image_magic
from worker.thumbnail import generate_single_thumbnail
import core.queue


class ProgressiveImporter:
    """Imports files progressively during gallery-dl download."""

    def __init__(self, db_job_id: str | None, user_id: int | None, *, page_num_from_filename: bool = False):
        self.db_job_id = db_job_id
        self.user_id = user_id
        self.gallery_id: int | None = None
        self.title: str | None = None
        self.source: str | None = None
        self.source_id: str | None = None
        self._processed: set[str] = set()
        self._page_counter = 0
        self.source_url: str | None = None
        self._sem = asyncio.Semaphore(2)
        self._job_started_at = datetime.now(UTC)
        self._tasks: list[asyncio.Task] = []
        self._page_num_from_filename = page_num_from_filename
        self._excluded_set: set[str] = set()

    async def _load_gallery_state(self) -> None:
        """Load excluded blobs and current max page_num for the gallery."""
        if not self.gallery_id:
            return
        async with AsyncSessionLocal() as session:
            from sqlalchemy import func

            rows = (
                (
                    await session.execute(
                        select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == self.gallery_id)
                    )
                )
                .scalars()
                .all()
            )
            self._excluded_set = set(rows)
            if self._excluded_set:
                logger.info(
                    "[progressive] loaded %d excluded blob(s) for gallery %d", len(self._excluded_set), self.gallery_id
                )

            # Resume page counter from current max page_num so new images don't collide
            max_page = (
                await session.execute(select(func.max(Image.page_num)).where(Image.gallery_id == self.gallery_id))
            ).scalar_one_or_none()
            if max_page and max_page > self._page_counter:
                self._page_counter = max_page
                logger.info("[progressive] resuming page counter at %d for gallery %d", max_page, self.gallery_id)

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
                    source_url=self.source_url,
                )
                .on_conflict_do_update(
                    index_elements=["source", "source_id"],
                    set_={
                        "title": pg_insert(Gallery).excluded.title,
                        "tags_array": pg_insert(Gallery).excluded.tags_array,
                        "download_status": "downloading",
                        "artist_id": pg_insert(Gallery).excluded.artist_id,
                        "source_url": pg_insert(Gallery).excluded.source_url,
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
        await self._load_gallery_state()
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
        for site in plugin_registry.get_all_sites():
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
                    source_url=self.source_url,
                )
                .on_conflict_do_update(
                    index_elements=["source", "source_id"],
                    set_={
                        "download_status": "downloading",
                        "source_url": pg_insert(Gallery).excluded.source_url,
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
        await self._load_gallery_state()
        return self.gallery_id

    async def ensure_gallery_from_import_data(self, data: GalleryImportData) -> int:
        """Create gallery from plugin-provided metadata (source-agnostic).

        Used by native plugins that can resolve metadata before download starts.
        """
        self.title = data.title
        self.source = data.source
        self.source_id = data.source_id

        async with AsyncSessionLocal() as session:
            stmt = (
                pg_insert(Gallery)
                .values(
                    source=data.source,
                    source_id=data.source_id,
                    title=data.title,
                    title_jpn=data.title_jpn,
                    category=data.category,
                    language=data.language,
                    pages=0,
                    posted_at=data.posted_at,
                    uploader=data.uploader,
                    download_status="downloading",
                    tags_array=data.tags,
                    artist_id=data.artist_id,
                    created_by_user_id=self.user_id,
                    source_url=self.source_url,
                )
                .on_conflict_do_update(
                    index_elements=["source", "source_id"],
                    set_={
                        "title": pg_insert(Gallery).excluded.title,
                        "tags_array": pg_insert(Gallery).excluded.tags_array,
                        "download_status": "downloading",
                        "artist_id": pg_insert(Gallery).excluded.artist_id,
                        "source_url": pg_insert(Gallery).excluded.source_url,
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

        logger.info("[progressive] gallery created from import data: id=%d title=%s", self.gallery_id, self.title)
        await self._load_gallery_state()
        return self.gallery_id

    async def import_file(self, file_path: Path, sha256: str | None = None) -> None:
        """Import a single media file with bounded concurrency.

        Page number is assigned here (serial caller) to guarantee deterministic
        ordering regardless of how tasks are scheduled.
        """
        str_path = str(file_path)
        if str_path in self._processed:
            return
        self._processed.add(str_path)

        # Assign page_num: from filename (for parallel downloaders like EH)
        # or serial counter (for sequential/streaming like gallery-dl)
        if self._page_num_from_filename:
            try:
                page_num = int(file_path.stem.lstrip("0") or "0") or 1
            except ValueError:
                self._page_counter += 1
                page_num = self._page_counter
        else:
            self._page_counter += 1
            page_num = self._page_counter

        # Prune completed tasks to avoid unbounded growth
        self._tasks = [t for t in self._tasks if not t.done()]

        async def _do_import():
            async with self._sem:
                await self._import_single(file_path, page_num, sha256=sha256)

        task = asyncio.create_task(_do_import())
        self._tasks.append(task)

    async def _import_single(self, file_path: Path, page_num: int, sha256: str | None = None) -> None:
        """Import one file: sha256 -> store_blob -> image record -> symlink -> thumbnail."""
        if not file_path.exists():
            return

        # Validate image magic bytes (skip check for videos)
        if file_path.suffix.lower() not in _VIDEO_EXTS:
            if not _validate_image_magic(file_path):
                logger.warning("[progressive] invalid magic bytes, skipping: %s", file_path.name)
                return

        try:
            final_sha256 = sha256 or await asyncio.to_thread(_sha256, file_path)

            # Skip excluded blobs
            if final_sha256 in self._excluded_set:
                logger.debug(
                    "[progressive] skipping excluded blob %s for gallery %d", final_sha256[:12], self.gallery_id
                )
                return

            async with AsyncSessionLocal() as session:
                blob = await store_blob(file_path, final_sha256, session)
                await session.flush()

                # N5: mtime PP sets original upload date
                try:
                    mtime = file_path.stat().st_mtime
                    added_at = datetime.fromtimestamp(mtime, tz=UTC)
                    if added_at.year < 2000 or added_at > datetime.now(UTC):
                        added_at = datetime.now(UTC)
                except (OSError, ValueError, OverflowError):
                    added_at = datetime.now(UTC)

                img_stmt = (
                    pg_insert(Image)
                    .values(
                        gallery_id=self.gallery_id,
                        page_num=page_num,
                        filename=file_path.name,
                        blob_sha256=final_sha256,
                        added_at=added_at,
                    )
                    .on_conflict_do_nothing()
                    .returning(Image.id)
                )
                result = await session.execute(img_stmt)
                inserted = result.scalar_one_or_none()

                if inserted is not None:
                    # New Image row was created — increment blob ref_count now.
                    await session.execute(
                        update(Blob).where(Blob.sha256 == final_sha256).values(ref_count=Blob.ref_count + 1)
                    )

                # Create library symlink before closing session (need blob data)
                await create_library_symlink(self.source, self.source_id, file_path.name, blob)

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

    async def _link_archive_entries(self, session) -> None:
        """Link gallery-dl archive entries to this gallery via gallery_id FK.

        Strategy 1: LIKE by source_id prefix (E-Hentai, Pixiv, booru).
        Strategy 2: job_id + time window (Twitter, etc.).
        """
        if not (self.gallery_id and self.source):
            return
        from sqlalchemy import text

        from plugins.builtin.gallery_dl._sites import get_site_config

        cfg = get_site_config(self.source)
        table = cfg.extractor or cfg.source_id

        try:
            exists = (
                await session.execute(
                    text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :t)"),
                    {"t": table},
                )
            ).scalar()
            if not exists:
                return

            # Strategy 1: LIKE match by source_id prefix
            if self.source_id:
                prefix = f"{self.source_id}%"
                result = await session.execute(
                    text(f'UPDATE "{table}" SET gallery_id = :gid WHERE gallery_id IS NULL AND entry LIKE :prefix'),
                    {"gid": self.gallery_id, "prefix": prefix},
                )
                if result.rowcount:
                    logger.info("[progressive] linked %d archive entries (prefix)", result.rowcount)
                    return

            # Strategy 2: time window + job_id exclusion
            if self.db_job_id:
                result = await session.execute(
                    text(
                        f'UPDATE "{table}" SET gallery_id = :gid, job_id = :jid '
                        f"WHERE gallery_id IS NULL AND job_id IS NULL "
                        f"AND created_at BETWEEN :start AND :end"
                    ),
                    {
                        "gid": self.gallery_id,
                        "jid": self.db_job_id,
                        "start": self._job_started_at,
                        "end": datetime.now(UTC),
                    },
                )
                if result.rowcount:
                    logger.info("[progressive] linked %d archive entries (job_id)", result.rowcount)

        except Exception as exc:
            logger.warning("[progressive] failed to link archive entries: %s", exc)

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
                count = (
                    await session.execute(select(func.count()).where(Image.gallery_id == self.gallery_id))
                ).scalar_one()
                gallery.pages = count
                gallery.download_status = "partial" if partial else "complete"
                gallery.metadata_updated_at = func.now()
                await self._link_archive_entries(session)
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
            await core.queue.enqueue("tag_job", gallery_id=self.gallery_id)

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
                count = (
                    await session.execute(select(func.count()).where(Image.gallery_id == self.gallery_id))
                ).scalar_one()
                gallery.pages = count
                gallery.download_status = "partial" if count > 0 else "downloading"
                await session.commit()

    async def cleanup(self) -> None:
        """Cancel pending tasks and fully delete the gallery. Called on user-initiated cancel.

        Decrements blob ref counts, deletes the gallery (CASCADE removes images),
        then removes the library symlink directory and thumbnail directories for
        any blobs that are now unreferenced.
        """
        import shutil

        from sqlalchemy.orm import selectinload

        # Cancel and drain any in-flight import tasks
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        if not self.gallery_id:
            return

        g_source = self.source
        g_source_id = self.source_id

        async with AsyncSessionLocal() as session:
            gallery = await session.get(Gallery, self.gallery_id)
            if not gallery:
                return

            # Load all images and their blobs before deleting DB records
            images_result = await session.execute(
                select(Image).where(Image.gallery_id == self.gallery_id).options(selectinload(Image.blob))
            )
            images = images_result.scalars().all()
            blob_sha256s = [img.blob_sha256 for img in images]

            # Decrement ref counts for all blobs
            for sha256 in blob_sha256s:
                await decrement_ref_count(sha256, session)

            # Delete gallery — CASCADE removes images, gallery_tags, read_progress
            await session.delete(gallery)
            await session.commit()

            # Determine which blobs are now unreferenced (safe to remove thumbs)
            zero_ref_sha256s: set[str] = set()
            if blob_sha256s:
                zero_ref_result = await session.execute(
                    select(Blob.sha256).where(Blob.sha256.in_(blob_sha256s), Blob.ref_count <= 0)
                )
                zero_ref_sha256s = set(zero_ref_result.scalars().all())

        logger.info(
            "[progressive] cleanup: deleted gallery_id=%d blobs=%d zero_ref=%d",
            self.gallery_id,
            len(blob_sha256s),
            len(zero_ref_sha256s),
        )

        def _delete_filesystem() -> None:
            # Remove the entire library symlink directory for this gallery
            if g_source and g_source_id:
                lib_dir = library_dir(g_source, g_source_id)
                if lib_dir.exists():
                    try:
                        shutil.rmtree(str(lib_dir), ignore_errors=True)
                    except OSError as exc:
                        logger.warning("[progressive] failed to remove library dir %s: %s", lib_dir, exc)

            # Only remove thumbnail directories for blobs that are no longer referenced
            for sha256 in zero_ref_sha256s:
                td = thumb_dir(sha256)
                if td.exists():
                    try:
                        shutil.rmtree(str(td), ignore_errors=True)
                    except OSError as exc:
                        logger.warning("[progressive] failed to remove thumb dir %s: %s", td, exc)

        try:
            await asyncio.to_thread(_delete_filesystem)
        except Exception as exc:
            logger.warning("[progressive] filesystem cleanup failed for gallery %d: %s", self.gallery_id, exc)
