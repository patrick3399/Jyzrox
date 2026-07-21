"""Progressive import: import files and generate thumbnails during download."""

import asyncio
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import select

import core.queue
from core.config import settings
from core.database import AsyncSessionLocal
from core.social_order import reorder_social_gallery_images
from db.models import ExcludedBlob, Gallery, Image
from plugins.models import GalleryImportData
from services.cas import (
    create_library_symlink,
    decrement_ref_count,
    increment_ref_count,
    library_dir,
    store_blob,
    thumb_dir,
)
from services.library_sidecar import sidecar_payload_from_gallery, write_gallery_sidecar
from services.thumbnail_lifecycle import cleanup_unreferenced_thumbnails
from worker.constants import _VIDEO_EXTS, logger
from worker.helpers import _sha256, _validate_image_magic

_FILENAME_NUMBER_RE = re.compile(r"(\d+)")
_PIXIV_USER_WORK_PAGE_RE = re.compile(r"^\d+_p\d+$")


def _subscription_artist_id(data: GalleryImportData, source_url: str | None) -> str | None:
    if data.artist_id:
        return data.artist_id
    if source_url and data.source and data.source_id:
        return f"{data.source}:{data.source_id}"
    return None


def _upsert_metadata_set(excluded, *, include_title_tags: bool) -> dict:
    """ON CONFLICT SET mapping shared by the ensure_gallery* upserts (BR-007).

    A re-download attaching to an existing gallery must not clobber non-empty
    metadata with blank values: empty/NULL title and empty tag arrays keep the
    existing row, artist_id only overwrites when the new value is non-NULL, and
    source_url is first-wins (the URL the gallery was originally created from).
    ``include_title_tags=False`` is for the URL-fallback path, whose title is
    derived from the URL path and must never overwrite real metadata.
    """
    from sqlalchemy import case, func

    set_: dict = {
        "download_status": "downloading",
        "artist_id": func.coalesce(excluded.artist_id, Gallery.artist_id),
        "source_url": func.coalesce(Gallery.source_url, excluded.source_url),
    }
    if include_title_tags:
        set_["title"] = func.coalesce(func.nullif(excluded.title, ""), Gallery.title)
        # cardinality(NULL) is NULL → condition falsy → existing tags kept.
        set_["tags_array"] = case(
            (func.cardinality(excluded.tags_array) > 0, excluded.tags_array),
            else_=Gallery.tags_array,
        )
    return set_


def _page_num_from_name(file_path: Path) -> int | None:
    """Extract the trailing numeric run from a filename stem for stable page order."""
    if _PIXIV_USER_WORK_PAGE_RE.match(file_path.stem):
        return None
    matches = _FILENAME_NUMBER_RE.findall(file_path.stem)
    if not matches:
        return None
    return int(matches[-1].lstrip("0") or "0") or 1


def _rmtree_staging_dir(dest_dir: Path) -> None:
    """Remove a per-download staging dir, refusing to delete the shared gallery root.

    A download whose ``dest_dir`` resolves to (or above) ``settings.data_gallery_path``
    would, via ``rmtree``, wipe every concurrently-downloading gallery's staging dir
    under the same root. Guard against that class of bug regardless of caller (e.g. a
    plugin whose ``resolve_output_dir`` mistakenly returns the root).
    """
    import shutil

    root = Path(settings.data_gallery_path).resolve()
    try:
        target = dest_dir.resolve()
    except OSError:
        target = dest_dir
    if target == root or target in root.parents:
        logger.error("[progressive] refusing to rmtree shared gallery root %s (dest_dir=%s)", root, dest_dir)
        return
    try:
        if dest_dir.exists():
            shutil.rmtree(str(dest_dir), ignore_errors=True)
    except Exception as exc:
        logger.warning("[progressive] failed to remove temp dir %s: %s", dest_dir, exc)


class ProgressiveImporter:
    """Imports files progressively during gallery-dl download."""

    def __init__(self, db_job_id: str | None, user_id: int | None, *, page_num_from_filename: bool = False):
        self.db_job_id = db_job_id
        self.user_id = user_id
        self.gallery_id: int | None = None
        self.title: str | None = None
        self.source: str | None = None
        self.source_id: str | None = None
        # Audit #8: a re-download/subscription run that targets a trashed gallery
        # (deleted_at set) must not mutate or resurrect it. When detected, the
        # importer records the trashed gallery id here, sets this flag, and turns
        # every mutating method (import_file/finalize/abort/cleanup) into a no-op.
        self.skipped_trashed: bool = False
        # Audit #53: when this run attaches to a pre-existing ACTIVE gallery
        # (re-download / subscription refresh), cancellation must roll back only
        # this run's additions instead of deleting the whole gallery. The
        # snapshot captures the row state to restore on cancel.
        self.pre_existing: bool = False
        self._prev_gallery_snapshot: dict | None = None
        self._preexisting_image_ids: set[int] = set()
        self._preexisting_active_count = 0
        self._preexisting_loaded = False
        self._processed: set[str] = set()
        self._page_counter = 0
        self.source_url: str | None = None
        self._sem = asyncio.Semaphore(2 if page_num_from_filename else 1)
        self._job_started_at = datetime.now(UTC)
        self._tasks: list[asyncio.Task] = []
        self._page_num_from_filename = page_num_from_filename
        self._excluded_set: set[str] = set()
        self._known_sha256s: set[str] = set()
        self._known_filenames: set[str] = set()
        self._known_source_items: set[str] = set()
        self._source_item_state: dict[str, tuple[int, str, str, int | None]] = {}
        self._skip_duplicate = 0
        self._skip_excluded = 0
        self._skip_invalid = 0
        # HR-002: per-file import failures (exception raised while importing a
        # downloaded file), plus a count of files that imported successfully
        # in this run. Used by finalize() to decide the terminal status
        # (complete / partial / failed) instead of always reporting complete.
        self._import_failures: list[dict[str, str]] = []
        self._import_success_count = 0
        # Set by finalize() to the resolved gallery.download_status; callers
        # (worker/download.py) read this to decide the DB DownloadJob status.
        self.download_status: str | None = None

    async def _load_gallery_state(self) -> None:
        """Load excluded blobs and current max page_num for the gallery.

        Also restores self.source / self.source_id from the gallery row when
        the importer was attached to a pre-existing gallery (e.g. subscription
        renew). Without this, import_file crashes in create_library_symlink
        with `Path / None` because the symlink layout is
        /data/library/{source}/{source_id}/.
        """
        if not self.gallery_id:
            return
        async with AsyncSessionLocal() as session:
            gallery = await session.get(Gallery, self.gallery_id)
            if gallery:
                if not self.source:
                    self.source = gallery.source
                if not self.source_id:
                    self.source_id = gallery.source_id
                if not self.title:
                    self.title = gallery.title

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

            existing_rows = (
                await session.execute(
                    select(
                        Image.id,
                        Image.page_num,
                        Image.blob_sha256,
                        Image.filename,
                        Image.source_item_id,
                        Image.visibility,
                    ).where(Image.gallery_id == self.gallery_id)
                )
            ).all()
            # Audit #53: remember which images pre-date this run, exactly once.
            # A second _load_gallery_state call (e.g. metadata arriving after the
            # URL-fallback attach) must not absorb this run's own images.
            if not self._preexisting_loaded:
                self._preexisting_image_ids = {row.id for row in existing_rows}
                self._preexisting_active_count = sum(1 for row in existing_rows if row.visibility == "active")
                self._preexisting_loaded = True

            self._known_sha256s = {row.blob_sha256 for row in existing_rows if row.blob_sha256}
            self._known_filenames = {row.filename for row in existing_rows if row.filename}
            self._known_source_items = {row.source_item_id for row in existing_rows if row.source_item_id}
            self._source_item_state = {
                row.source_item_id: (row.id, row.blob_sha256, row.visibility, row.page_num)
                for row in existing_rows
                if row.source_item_id
            }

            # Resume page counter from current max page_num so new images don't collide
            max_page = max((row.page_num for row in existing_rows), default=0)
            if max_page and max_page > self._page_counter:
                self._page_counter = max_page
                logger.info("[progressive] resuming page counter at %d for gallery %d", max_page, self.gallery_id)

    async def attach_existing_gallery(self, gallery_id: int) -> bool:
        """Attach to a gallery persisted on a previous attempt without owning it.

        Retry/resume reconstructs the importer from ``DownloadJob.gallery_id``
        and therefore bypasses the normal ``ensure_gallery*`` conflict lookup.
        Treat that row as pre-existing for this attempt: snapshot it before any
        mutation so cancellation can roll back only this attempt's additions.
        Returns False when the row no longer exists.
        """
        async with AsyncSessionLocal() as session:
            gallery = await session.get(Gallery, gallery_id)
            if gallery is None:
                return False

            self.gallery_id = gallery.id
            self.source = gallery.source
            self.source_id = gallery.source_id
            self.title = gallery.title
            if gallery.deleted_at is not None:
                self.skipped_trashed = True
            else:
                self.pre_existing = True
                self._prev_gallery_snapshot = {
                    "download_status": gallery.download_status,
                    "title": gallery.title,
                    "tags_array": gallery.tags_array,
                    "source_url": gallery.source_url,
                    "artist_id": gallery.artist_id,
                }

        await self._load_gallery_state()
        return True

    @property
    def import_failures(self) -> tuple[dict[str, str], ...]:
        """Return an immutable snapshot of per-file import failures."""
        return tuple(dict(item) for item in self._import_failures)

    @property
    def import_success_count(self) -> int:
        """Return the number of files committed successfully in this run."""
        return self._import_success_count

    @property
    def skipped_duplicate_count(self) -> int:
        return self._skip_duplicate

    @property
    def skipped_excluded_count(self) -> int:
        return self._skip_excluded

    @property
    def skipped_invalid_count(self) -> int:
        return self._skip_invalid

    async def _detect_trashed_conflict(self, session, source: str, source_id: str) -> int | None:
        """Audit #8: return the id of an existing *trashed* gallery for this
        (source, source_id), or None.

        When a re-download or subscription run upserts by (source, source_id),
        the conflict target may be a gallery the user sent to trash. Mutating it
        would silently resurrect content / flip status (the same invariant the
        rescan path hardened in #58 / BE-T16). Callers must skip the upsert and
        all imports when this returns a non-None id.
        """
        existing = (
            await session.execute(
                select(
                    Gallery.id,
                    Gallery.deleted_at,
                    Gallery.download_status,
                    Gallery.title,
                    Gallery.tags_array,
                    Gallery.source_url,
                    Gallery.artist_id,
                    Gallery.pages,
                ).where(Gallery.source == source, Gallery.source_id == source_id)
            )
        ).first()
        if existing is not None and existing.deleted_at is None and self.gallery_id is None:
            # Audit #53: this run is attaching to a pre-existing active gallery.
            # Snapshot it so a user cancel can restore instead of delete. Only
            # on first attach — a later ensure_gallery* call for a gallery this
            # run itself created must not flip the run to pre-existing.
            self.pre_existing = True
            self._prev_gallery_snapshot = {
                "download_status": existing.download_status,
                "title": existing.title,
                "tags_array": existing.tags_array,
                "source_url": existing.source_url,
                "artist_id": existing.artist_id,
            }
        if existing is not None and existing.deleted_at is not None:
            self.gallery_id = existing.id
            self.skipped_trashed = True
            logger.info(
                "[progressive] skipping import into trashed gallery id=%d (%s:%s); restore it first",
                existing.id,
                source,
                source_id,
            )
            return existing.id
        return None

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
            trashed_id = await self._detect_trashed_conflict(session, import_data.source, import_data.source_id)
            if trashed_id is not None:
                return trashed_id
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
                    artist_id=_subscription_artist_id(import_data, self.source_url),
                    created_by_user_id=self.user_id,
                    source_url=self.source_url,
                )
                .on_conflict_do_update(
                    index_elements=["source", "source_id"],
                    set_=_upsert_metadata_set(pg_insert(Gallery).excluded, include_title_tags=True),
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

        from plugins.builtin.gallery_dl._sites import get_site_by_domain

        parsed = urlparse(url)
        domain = parsed.netloc.removeprefix("www.")

        from plugins.builtin.gallery_dl._sites import _DEFAULT_CONFIG

        site_cfg = get_site_by_domain(domain)
        # For unknown domains use the bare domain as source (e.g. "somebooru.net")
        # so galleries aren't all lumped under "gallery_dl".
        source = domain if site_cfg is _DEFAULT_CONFIG else site_cfg.source_id

        # Derive source_id from URL path, respecting per-site path segment index.
        # E.g. weibo.com/u/USERID: url_path_id_index=1 skips the "u" routing prefix.
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        id_idx = min(site_cfg.url_path_id_index, len(path_parts) - 1) if path_parts else 0
        source_id = path_parts[id_idx] if path_parts else dest_dir.name
        title = source_id

        self.title = title
        self.source = source
        self.source_id = source_id

        async with AsyncSessionLocal() as session:
            trashed_id = await self._detect_trashed_conflict(session, source, source_id)
            if trashed_id is not None:
                return trashed_id
            stmt = (
                pg_insert(Gallery)
                .values(
                    source=source,
                    source_id=source_id,
                    title=title,
                    pages=0,
                    download_status="downloading",
                    artist_id=f"{source}:{source_id}" if self.source_url and source and source_id else None,
                    created_by_user_id=self.user_id,
                    source_url=self.source_url,
                )
                .on_conflict_do_update(
                    index_elements=["source", "source_id"],
                    set_=_upsert_metadata_set(pg_insert(Gallery).excluded, include_title_tags=False),
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
            trashed_id = await self._detect_trashed_conflict(session, data.source, data.source_id)
            if trashed_id is not None:
                return trashed_id
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
                    artist_id=_subscription_artist_id(data, self.source_url),
                    created_by_user_id=self.user_id,
                    source_url=self.source_url,
                )
                .on_conflict_do_update(
                    index_elements=["source", "source_id"],
                    set_=_upsert_metadata_set(pg_insert(Gallery).excluded, include_title_tags=True),
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
        # Audit #8: never import into a trashed gallery.
        if self.skipped_trashed:
            return
        str_path = str(file_path)
        if str_path in self._processed:
            return
        self._processed.add(str_path)

        # Assign page_num from filename for parallel downloaders like EH.
        # Sequential downloaders assign after validation so skipped files do not
        # leave holes in page numbering.
        page_num: int | None
        if self._page_num_from_filename:
            page_num = _page_num_from_name(file_path)
            if page_num is None:
                self._page_counter += 1
                page_num = self._page_counter
        else:
            page_num = None

        # Prune completed tasks to avoid unbounded growth
        self._tasks = [t for t in self._tasks if not t.done()]

        async def _do_import():
            async with self._sem:
                try:
                    await self._import_single(file_path, page_num, sha256=sha256)
                except Exception as exc:
                    # Defensive: _import_single already catches its own errors
                    # and records them below. This is a backstop for anything
                    # that escapes it (e.g. semaphore/session-teardown bugs)
                    # so finalize()'s gather never silently swallows a failure.
                    logger.warning("[progressive] task error importing %s: %s", file_path.name, exc)
                    self._import_failures.append(
                        {
                            "filename": file_path.name,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )

        task = asyncio.create_task(_do_import())
        self._tasks.append(task)

    async def _import_single(self, file_path: Path, page_num: int | None, sha256: str | None = None) -> None:
        """Import one file: sha256 -> store_blob -> image record -> symlink."""
        if not file_path.exists():
            return

        # Validate image magic bytes (skip check for videos)
        if file_path.suffix.lower() not in _VIDEO_EXTS:
            if not _validate_image_magic(file_path):
                self._skip_invalid += 1
                logger.warning("[progressive] invalid magic bytes, skipping: %s", file_path.name)
                return

        try:
            final_sha256 = sha256 or await asyncio.to_thread(_sha256, file_path)
            source_item_id = self._derive_source_item_id(file_path, page_num, final_sha256)

            # Skip excluded blobs
            if final_sha256 in self._excluded_set:
                self._skip_excluded += 1
                return
            existing_source_item = self._source_item_state.get(source_item_id) if source_item_id else None
            if final_sha256 in self._known_sha256s:
                self._skip_duplicate += 1
                return
            if existing_source_item and existing_source_item[1] == final_sha256:
                await self._touch_existing_source_item(existing_source_item[0], existing_source_item[2], page_num)
                self._skip_duplicate += 1
                return
            if not existing_source_item and file_path.name in self._known_filenames:
                self._skip_duplicate += 1
                return

            async with AsyncSessionLocal() as session:
                blob = await store_blob(file_path, final_sha256, session)
                await session.flush()

                replacement_image: Image | None = None
                if existing_source_item:
                    replacement_image = await session.get(
                        Image, existing_source_item[0], options=[selectinload(Image.blob)]
                    )
                    if replacement_image:
                        page_num = replacement_image.page_num
                        replacement_visibility = (
                            "user_hidden" if replacement_image.visibility == "user_hidden" else "active"
                        )
                        replacement_image.visibility = "replaced"
                        replacement_image.page_num = -replacement_image.id
                    else:
                        replacement_visibility = "active"
                else:
                    replacement_visibility = "active"

                if page_num is None:
                    self._page_counter += 1
                    page_num = self._page_counter

                # N5: mtime PP sets original upload date
                try:
                    mtime = file_path.stat().st_mtime
                    added_at = datetime.fromtimestamp(mtime, tz=UTC)
                    if added_at.year < 2000 or added_at > datetime.now(UTC):
                        added_at = datetime.now(UTC)
                except OSError, ValueError, OverflowError:
                    added_at = datetime.now(UTC)

                img_stmt = (
                    pg_insert(Image)
                    .values(
                        gallery_id=self.gallery_id,
                        page_num=page_num,
                        filename=file_path.name,
                        blob_sha256=final_sha256,
                        added_at=added_at,
                        visibility=replacement_visibility,
                        source_item_id=source_item_id,
                        source_position=page_num,
                        source_seen_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing()
                    .returning(Image.id)
                )
                result = await session.execute(img_stmt)
                inserted = result.scalar_one_or_none()

                if inserted is not None:
                    # New Image row was created — increment blob ref_count now.
                    await increment_ref_count(final_sha256, session)
                    self._known_sha256s.add(final_sha256)
                    self._known_filenames.add(file_path.name)
                    if source_item_id:
                        self._known_source_items.add(source_item_id)
                        self._source_item_state[source_item_id] = (
                            inserted,
                            final_sha256,
                            replacement_visibility,
                            page_num,
                        )
                    if replacement_image is not None:
                        replacement_image.replaced_by_image_id = inserted

                    # Create library symlink before closing session (need blob data).
                    # Only when a row was actually inserted — a conflicting insert
                    # must not leave a symlink the DB does not represent (edge case #48).
                    await create_library_symlink(self.source, self.source_id, file_path.name, blob)
                await session.commit()

            if inserted is not None:
                self._import_success_count += 1
            logger.info("[progressive] imported: %s (page %d)", file_path.name, page_num)

        except Exception as exc:
            logger.warning("[progressive] failed to import %s: %s", file_path.name, exc)
            self._import_failures.append(
                {
                    "filename": file_path.name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    async def _touch_existing_source_item(self, image_id: int, visibility: str, page_num: int | None) -> None:
        """Refresh seen metadata for a source item that was already imported."""
        async with AsyncSessionLocal() as session:
            img = await session.get(Image, image_id)
            if not img:
                return
            img.source_seen_at = datetime.now(UTC)
            if page_num is not None:
                img.source_position = page_num
            if visibility == "source_missing":
                img.visibility = "active"
            await session.commit()

    def _derive_source_item_id(self, file_path: Path, page_num: int | None, sha256: str) -> str:
        """Best-effort stable identity for source sync and duplicate guards."""
        source = self.source or "unknown"
        if source == "pixiv":
            stem = file_path.stem
            parent = file_path.parent.name
            if "_p" in stem:
                illust_id, _, page_part = stem.rpartition("_p")
                try:
                    page_idx = int(page_part.lstrip("0") or "0") or 1
                    return f"pixiv:{illust_id}:p{page_idx}"
                except ValueError:
                    return f"pixiv:{stem}"
            if parent.isdigit() and page_num is not None:
                return f"pixiv:{parent}:p{page_num}"
            if self.source_id and page_num is not None:
                return f"pixiv:{self.source_id}:p{page_num}"
        if source == "ehentai" and self.source_id and page_num is not None:
            return f"ehentai:{self.source_id}:p{page_num}"
        if page_num is not None:
            return f"{source}:{self.source_id or 'unknown'}:{file_path.name}:p{page_num}"
        return f"{source}:{self.source_id or 'unknown'}:{sha256}"

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
            async with session.begin_nested():  # SAVEPOINT: failure rolls back only this block
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

        # Audit #8: trashed gallery — nothing was imported, so do not mutate the
        # gallery row or enqueue cover/thumbnail/tag jobs. Just drop the temp dir.
        if self.skipped_trashed:
            _rmtree_staging_dir(dest_dir)
            return None

        if not self.gallery_id:
            return None

        # HR-002: derive the terminal status from actual per-file outcomes
        # instead of always reporting "complete". Any recorded failure makes
        # the run "partial"; if every attempted file failed and none
        # succeeded in this run, it is "failed" outright — this overrides a
        # caller-requested "partial" since it is a worse outcome.
        if self._import_failures and self._import_success_count == 0:
            resolved_status = "failed"
        elif partial or self._import_failures:
            resolved_status = "partial"
        else:
            resolved_status = "complete"
        self.download_status = resolved_status

        async with AsyncSessionLocal() as session:
            from sqlalchemy import func

            gallery = await session.get(Gallery, self.gallery_id)
            if gallery:
                await reorder_social_gallery_images(session, self.gallery_id, gallery.source)
                count = (
                    await session.execute(
                        select(func.count()).where(Image.gallery_id == self.gallery_id, Image.visibility == "active")
                    )
                ).scalar_one()
                gallery.pages = count
                gallery.download_status = resolved_status
                gallery.metadata_updated_at = func.now()
                await self._link_archive_entries(session)
                # Capture before commit: attributes expire on commit
                sidecar_source, sidecar_source_id = gallery.source, gallery.source_id
                sidecar_payload = sidecar_payload_from_gallery(gallery)
                await session.commit()
                # Disaster-recovery sidecar (best-effort)
                await write_gallery_sidecar(sidecar_source, sidecar_source_id, sidecar_payload)

        from services.gallery_lifecycle import invalidate_sources_cache

        await invalidate_sources_cache()

        _rmtree_staging_dir(dest_dir)

        skip_parts = []
        if self._skip_duplicate:
            skip_parts.append(f"duplicate={self._skip_duplicate}")
        if self._skip_excluded:
            skip_parts.append(f"excluded={self._skip_excluded}")
        if self._skip_invalid:
            skip_parts.append(f"invalid={self._skip_invalid}")
        skip_summary = f" skipped({', '.join(skip_parts)})" if skip_parts else ""
        logger.info(
            "[progressive] finalized: gallery_id=%d pages=%d%s", self.gallery_id, self._page_counter, skip_summary
        )

        from core.config import settings

        await core.queue.enqueue(
            "cover_thumbnail_job",
            gallery_id=self.gallery_id,
            _timeout=300,
            _job_id=f"cover-thumbnail:{self.gallery_id}",
        )
        await core.queue.enqueue(
            "thumbnail_job",
            gallery_id=self.gallery_id,
            _timeout=3600,
            _job_id=f"thumbnail:{self.gallery_id}",
        )

        if settings.tag_model_enabled:
            await core.queue.enqueue("tag_job", gallery_id=self.gallery_id)

        return self.gallery_id

    async def abort(self) -> None:
        """Cancel pending tasks and set gallery status to 'partial'. Called on failure/cancellation."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        # Audit #8: never mutate a trashed gallery's status on abort.
        if self.skipped_trashed:
            return

        if not self.gallery_id:
            return

        async with AsyncSessionLocal() as session:
            from sqlalchemy import func

            gallery = await session.get(Gallery, self.gallery_id)
            if gallery:
                count = (
                    await session.execute(
                        select(func.count()).where(Image.gallery_id == self.gallery_id, Image.visibility == "active")
                    )
                ).scalar_one()
                gallery.pages = count
                if self.pre_existing and self._prev_gallery_snapshot and count == self._preexisting_active_count:
                    # Audit #53: a cancelled/failed refresh that added nothing must
                    # not demote the pre-existing gallery's status (complete → partial).
                    gallery.download_status = self._prev_gallery_snapshot["download_status"]
                else:
                    gallery.download_status = "partial" if count > 0 else "failed"
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

        # Audit #8 / #53: a skipped trashed gallery pre-existed this job and had
        # nothing imported into it — cancelling must never delete it.
        if self.skipped_trashed:
            return

        if not self.gallery_id:
            return

        # Audit #53: a re-download attached to a pre-existing active gallery
        # must not delete it on cancel — roll back only what this run added.
        if self.pre_existing:
            await self._cleanup_partial_run()
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
            zero_ref_sha256s = await cleanup_unreferenced_thumbnails(
                session,
                blob_sha256s,
                directory_resolver=thumb_dir,
            )

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

        try:
            await asyncio.to_thread(_delete_filesystem)
        except Exception as exc:
            logger.warning("[progressive] filesystem cleanup failed for gallery %d: %s", self.gallery_id, exc)

    async def _cleanup_partial_run(self) -> None:
        """Roll back a cancelled run that attached to a pre-existing gallery.

        Audit #53: deletes only this run's images, decrements only their blob
        refs, removes only their symlinks and now-unreferenced thumb dirs, and
        restores the pre-run gallery snapshot. The gallery row and its prior
        images survive.
        """

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
            if not gallery:
                return

            stmt = select(Image).where(Image.gallery_id == self.gallery_id)
            if self._preexisting_image_ids:
                stmt = stmt.where(Image.id.not_in(self._preexisting_image_ids))
            new_images = (await session.execute(stmt)).scalars().all()

            removed_names = [img.filename for img in new_images if img.filename]
            removed_shas = [img.blob_sha256 for img in new_images if img.blob_sha256]
            for img in new_images:
                await session.delete(img)
            for sha256 in removed_shas:
                await decrement_ref_count(sha256, session)

            snap = self._prev_gallery_snapshot or {}
            if snap:
                gallery.title = snap["title"]
                gallery.tags_array = snap["tags_array"]
                gallery.source_url = snap["source_url"]
                gallery.artist_id = snap["artist_id"]
                gallery.download_status = snap["download_status"]
            count = (
                await session.execute(
                    select(func.count()).where(Image.gallery_id == self.gallery_id, Image.visibility == "active")
                )
            ).scalar_one()
            gallery.pages = count
            await session.commit()
            zero_ref_sha256s = await cleanup_unreferenced_thumbnails(
                session,
                removed_shas,
                directory_resolver=thumb_dir,
            )

        logger.info(
            "[progressive] partial-run cleanup: gallery_id=%d kept, removed_images=%d zero_ref=%d",
            self.gallery_id,
            len(removed_names),
            len(zero_ref_sha256s),
        )

        lib_dir = library_dir(self.source, self.source_id) if self.source and self.source_id else None

        def _remove_run_artifacts() -> None:
            if lib_dir is not None:
                for name in removed_names:
                    try:
                        (lib_dir / name).unlink(missing_ok=True)
                    except OSError as exc:
                        logger.warning("[progressive] failed to remove symlink %s: %s", lib_dir / name, exc)

        try:
            await asyncio.to_thread(_remove_run_artifacts)
        except Exception as exc:
            logger.warning("[progressive] partial-run fs cleanup failed for gallery %d: %s", self.gallery_id, exc)
