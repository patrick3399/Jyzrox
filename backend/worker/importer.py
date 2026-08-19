"""Import jobs for the worker package."""

import asyncio
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

import core.queue
from core.config import settings
from core.database import AsyncSessionLocal
from core.social_order import reorder_social_gallery_images
from db.models import Blob, ExcludedBlob, Gallery, Image, ImportConflict
from services.cas import (
    create_library_symlink,
    increment_ref_count,
    library_dir,
    store_blob,
    thumb_dir,
    thumbnails_complete_at,
)
from services.library_sidecar import sidecar_payload_from_gallery, write_gallery_sidecar
from services.tag_helpers import (
    rebuild_gallery_tags_array,
    upsert_metadata_gallery_tags,
    upsert_tag_translations,
)
from worker.constants import (
    _MEDIA_EXTS,
    _VIDEO_EXTS,
    logger,
)
from worker.helpers import _sha256, _validate_image_magic
from worker.source_identity import (
    SourceDirectoryChangedError,
    SourceDirectoryIdentity,
    SourceFileChangedError,
    SourceFileIdentity,
    hash_file_with_identity,
)

_NATURAL_SORT_RE = re.compile(r"(\d+)")


def _subscription_artist_id(source: str, source_id: str, artist_id: str | None, source_url: str | None) -> str | None:
    if artist_id:
        return artist_id
    if source_url and source and source_id:
        return f"{source}:{source_id}"
    return None


def _natural_sort_key(path: Path) -> tuple[tuple[int, str | int], ...]:
    """Sort filenames in human page order: 1, 2, 10 instead of 1, 10, 2."""
    parts = _NATURAL_SORT_RE.split(path.name)
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold()) for part in parts)


def _restore_library_links(states: list[tuple[Path, str | None]]) -> None:
    """Best-effort rollback for deferred link-import symlinks."""
    for link, previous_target in reversed(states):
        try:
            if link.is_symlink():
                link.unlink()
            if previous_target is not None:
                link.symlink_to(previous_target)
        except OSError as exc:
            logger.error("[local_import] failed to restore library link %s: %s", link, exc)


def _disambiguate_library_filenames(paths: list[Path]) -> list[str]:
    """Map each media file to a unique library filename (edge case #47).

    Recursive imports can contain the same basename in different
    subdirectories, and library symlinks are keyed by filename only — without
    disambiguation the last symlink silently replaces the others while the DB
    keeps one image row per file. First occurrence keeps its basename; later
    duplicates get a numbered suffix before the extension.
    """
    used: set[str] = set()
    names: list[str] = []
    for p in paths:
        name = p.name
        if name in used:
            n = 2
            while (candidate := f"{p.stem}__{n}{p.suffix}") in used:
                n += 1
            name = candidate
        used.add(name)
        names.append(name)
    return names


async def import_job(
    ctx: dict, path: str, db_job_id: str | None = None, user_id: int | None = None, source_url: str | None = None
) -> dict:
    """
    Ingest a downloaded gallery directory into the database.
    Handles gallery-dl E-Hentai and Pixiv output formats.
    """
    gallery_path = Path(path)
    logger.info("[import] path=%s", gallery_path)

    if not gallery_path.is_dir():
        return {"status": "failed", "error": f"not a directory: {path}"}

    # Read gallery-dl metadata (any .json file, they all have gallery info)
    metadata: dict = {}
    for meta_file in sorted(gallery_path.rglob("*.json")):
        try:
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            break
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            logger.warning("[import] failed to read metadata %s: %s", meta_file, exc)
            continue

    # Extract source from Category (gallery-dl uses "category" for the extractor name)
    raw_source = metadata.get("category")
    if not raw_source:
        # Fallback heuristic: infer source from download directory path
        parts = gallery_path.parts
        if "ehentai" in parts:
            raw_source = "ehentai"
        elif "pixiv" in parts:
            raw_source = "pixiv"
        else:
            raw_source = "gallery_dl"

    # Resolve to canonical source_id (e.g., "exhentai" → "ehentai")
    from plugins.builtin.gallery_dl._sites import get_site_config as _get_site_config

    _cfg = _get_site_config(raw_source)
    source = _cfg.source_id
    source_id = gallery_path.name
    for _field in _cfg.source_id_fields:
        _val = metadata.get(_field)
        if _val:
            source_id = str(_val)
            break

    tags = _normalize_tags(_extract_tags(gallery_path, metadata), source)
    media_files_raw = [f for f in gallery_path.rglob("*") if f.is_file() and f.suffix.lower() in _MEDIA_EXTS]
    # Validate magic bytes for images; pass video files through without check
    media_files = []
    skipped = 0
    for f in media_files_raw:
        if f.suffix.lower() in _VIDEO_EXTS or _validate_image_magic(f):
            media_files.append(f)
        else:
            skipped += 1
    media_files.sort(key=_natural_sort_key)
    if skipped:
        logger.warning("[import] %s: skipped %d file(s) with invalid magic bytes", gallery_path.name, skipped)

    if not media_files:
        return {"status": "failed", "error": "no media files found"}

    import shutil as _shutil

    async with AsyncSessionLocal() as session:
        # Try Parseable plugin first, fallback to legacy _build_gallery
        from plugins.registry import plugin_registry

        parser = plugin_registry.get_parser(source)
        if parser:
            from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

            import_data = parse_gallery_dl_import(gallery_path, metadata, fallback_source=source)
            gallery_values = {
                "source": import_data.source,
                "source_id": import_data.source_id,
                "title": import_data.title,
                "title_jpn": import_data.title_jpn,
                "category": import_data.category,
                "language": import_data.language,
                "pages": 0,
                "posted_at": import_data.posted_at,
                "uploader": import_data.uploader,
                "download_status": "importing",
                "metadata_updated_at": func.now(),
                "tags_array": import_data.tags,
                "artist_id": _subscription_artist_id(
                    import_data.source, import_data.source_id, import_data.artist_id, source_url
                ),
                "created_by_user_id": user_id,
                "source_url": source_url,
            }
            tags = import_data.tags
            source_id = import_data.source_id
        else:
            gallery_values = _build_gallery(source, source_id, metadata, tags, 0)
            gallery_values["download_status"] = "importing"
            gallery_values["created_by_user_id"] = user_id
            gallery_values["source_url"] = source_url
            gallery_values["artist_id"] = _subscription_artist_id(
                gallery_values["source"],
                gallery_values["source_id"],
                gallery_values["artist_id"],
                source_url,
            )
        stmt = (
            pg_insert(Gallery)
            .values(**gallery_values)
            .on_conflict_do_update(
                index_elements=["source", "source_id"],
                set_={
                    "title": pg_insert(Gallery).excluded.title,
                    "tags_array": pg_insert(Gallery).excluded.tags_array,
                    "download_status": "importing",
                    "metadata_updated_at": func.now(),
                    "pages": Gallery.pages,
                    "artist_id": pg_insert(Gallery).excluded.artist_id,
                    "source_url": pg_insert(Gallery).excluded.source_url,
                },
                where=Gallery.deleted_at.is_(None),
            )
            .returning(Gallery.id)
        )
        gallery_id = (await session.execute(stmt)).scalar_one_or_none()
        if gallery_id is None:
            await session.rollback()
            logger.warning(
                "[import] refusing to mutate trashed gallery for source=%s source_id=%s",
                gallery_values["source"],
                gallery_values["source_id"],
            )
            return {
                "status": "skipped_trashed",
                "source": gallery_values["source"],
                "source_id": gallery_values["source_id"],
            }

        # Load excluded blob hashes for this gallery
        excluded_rows = (
            (await session.execute(select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == gallery_id)))
            .scalars()
            .all()
        )
        excluded_set: set[str] = set(excluded_rows)

        # Compute hashes with bounded concurrency to avoid thread pool exhaustion
        _hash_sem = asyncio.Semaphore(10)

        hash_failures: list[dict[str, str]] = []

        async def _sha256_limited(f):
            async with _hash_sem:
                try:
                    return await asyncio.to_thread(_sha256, f)
                except (FileNotFoundError, OSError) as exc:
                    logger.warning("[import] skipping deleted file %s: %s", f.name, exc)
                    hash_failures.append(
                        {
                            "filename": f.name,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                    return None

        hashes = await asyncio.gather(*[_sha256_limited(f) for f in media_files])

        allowed_pairs = [
            (img_file, sha256)
            for img_file, sha256 in zip(media_files, hashes, strict=False)
            if sha256 is not None and sha256 not in excluded_set
        ]
        if len(allowed_pairs) < len(media_files):
            logger.info(
                "[import] gallery_id=%d: skipped %d excluded blob(s)",
                gallery_id,
                len(media_files) - len(allowed_pairs),
            )

        # Duplicate basenames from recursive downloads must not overwrite each
        # other's symlink; the disambiguated name is also stored as the Image
        # filename so disk and DB stay in agreement (edge case #47).
        library_names = _disambiguate_library_filenames([img_file for img_file, _ in allowed_pairs])

        # Store each file in CAS and create library symlink
        for (img_file, sha256), lib_name in zip(allowed_pairs, library_names, strict=True):
            blob = await store_blob(img_file, sha256, session)
            await create_library_symlink(source, source_id, lib_name, blob)

        # Flush blob upserts before inserting images (FK: blob_sha256 → blobs.sha256)
        await session.flush()

        # Bulk-insert images
        now = datetime.now(UTC)
        image_values = [
            {
                "gallery_id": gallery_id,
                "page_num": page_num,
                "source_position": page_num,
                "filename": lib_name,
                "blob_sha256": sha256,
                "added_at": now,
            }
            for page_num, ((_img_file, sha256), lib_name) in enumerate(
                zip(allowed_pairs, library_names, strict=True), start=1
            )
        ]
        inserted_rows = []
        if image_values:
            img_stmt = (
                pg_insert(Image).values(image_values).on_conflict_do_nothing().returning(Image.id, Image.blob_sha256)
            )
            result = await session.execute(img_stmt)
            inserted_rows = result.all()

            if inserted_rows:
                # Only increment ref_count for blobs that got a new Image row.
                sha_counts = Counter(row.blob_sha256 for row in inserted_rows)
                for sha, count in sha_counts.items():
                    await increment_ref_count(sha, session, count)

        actual_pages = (
            await session.execute(
                select(func.count(Image.id)).where(Image.gallery_id == gallery_id, Image.visibility == "active")
            )
        ).scalar_one()
        if hash_failures and not allowed_pairs:
            terminal_status = "failed"
        elif hash_failures:
            terminal_status = "partial"
        else:
            terminal_status = "complete"
        gallery = await session.get(Gallery, gallery_id)
        if gallery:
            gallery.pages = actual_pages
            gallery.download_status = terminal_status

        # Upsert tags + gallery_tags
        await upsert_metadata_gallery_tags(session, gallery_id, tags)

        await reorder_social_gallery_images(session, gallery_id, source)

        # Upsert tag translations if present in metadata
        tag_translations = metadata.get("tag_translations")
        if tag_translations:
            await upsert_tag_translations(session, tag_translations)

        # Rebuild tags_array from gallery_tags (single source of truth)
        await rebuild_gallery_tags_array(session, gallery_id)

        await session.commit()

    # Disaster-recovery sidecar: identifies the gallery when only the library
    # tree survives a DB loss. Built from local values (best-effort write).
    _posted_at = gallery_values.get("posted_at")
    await write_gallery_sidecar(
        source,
        source_id,
        {
            "title": gallery_values.get("title"),
            "title_jpn": gallery_values.get("title_jpn"),
            "source": source,
            "source_id": source_id,
            "category": gallery_values.get("category"),
            "language": gallery_values.get("language"),
            "uploader": gallery_values.get("uploader"),
            "artist_id": gallery_values.get("artist_id"),
            "pages": actual_pages,
            "source_url": source_url,
            "tags": list(tags),
            "posted_at": _posted_at.isoformat() if _posted_at is not None else None,
        },
    )

    # Preserve staging whenever a file could not be ingested so an operator can
    # retry or recover it. A fully successful import may remove the temporary
    # download directory as before.
    if not hash_failures:
        try:
            _shutil.rmtree(str(gallery_path), ignore_errors=True)
        except Exception as exc:
            logger.warning("[import] failed to remove temp dir %s: %s", gallery_path, exc)

    logger.info("[import] gallery_id=%d source=%s/%s", gallery_id, source, source_id)

    from services.gallery_lifecycle import invalidate_sources_cache

    await invalidate_sources_cache()

    # Trigger thumbnail generation
    await core.queue.enqueue(
        "cover_thumbnail_job",
        gallery_id=gallery_id,
        _timeout=300,
        _job_id=f"cover-thumbnail:{gallery_id}",
    )
    await core.queue.enqueue(
        "thumbnail_job",
        gallery_id=gallery_id,
        _timeout=3600,
        _job_id=f"thumbnail:{gallery_id}",
    )
    if settings.tag_model_enabled:
        await core.queue.enqueue("tag_job", gallery_id=gallery_id)

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.IMPORT_COMPLETED,
        resource_type="gallery",
        resource_id=gallery_id,
        pages=actual_pages,
        source=source,
    )

    return {
        "status": "done" if terminal_status == "complete" else terminal_status,
        "gallery_id": gallery_id,
        "pages": actual_pages,
        "import_failures": hash_failures,
    }


def _extract_tags(gallery_path: Path, metadata: dict) -> list[str]:
    """Extract tags in 'namespace:name' format from metadata or tags.txt."""
    tags: list[str] = []

    raw = metadata.get("tags")
    if isinstance(raw, dict):
        for ns, names in raw.items():
            tags.extend(f"{ns}:{n}" for n in names)
    elif isinstance(raw, list):
        tags.extend(raw)

    if not tags:
        tags_file = gallery_path / "tags.txt"
        if tags_file.exists():
            tags = [t.strip() for t in tags_file.read_text().splitlines() if t.strip()]

    return tags


def _normalize_tags(tags: list[str], source: str) -> list[str]:
    """Normalize namespace names across sources for consistency."""
    from plugins.builtin.gallery_dl._metadata import _normalize_tags as _meta_normalize_tags

    return _meta_normalize_tags(tags, source)


def _build_gallery(
    source: str,
    source_id: str,
    meta: dict,
    tags: list[str],
    page_count: int,
) -> dict:
    posted_at = None
    raw_date = meta.get("date") or meta.get("posted")
    if raw_date:
        try:
            if isinstance(raw_date, int | float):
                posted_at = datetime.fromtimestamp(raw_date, tz=UTC)
            else:
                posted_at = datetime.fromisoformat(str(raw_date))
        except (ValueError, TypeError, OverflowError) as exc:
            logger.warning("[import] failed to parse date %r: %s", raw_date, exc)

    # Artist ID extraction — delegate to shared logic
    # ehentai and pixiv are now in _sites.py so _extract_artist handles them correctly
    from plugins.builtin.gallery_dl._metadata import _extract_artist

    artist_id = _extract_artist(source, meta, tags)

    return {
        "source": source,
        "source_id": source_id,
        "title": (
            meta.get("title")
            or meta.get("title_en")
            or (meta.get("description") or "")[:120]
            or (meta.get("content") or "")[:120]
            or f"{source}_{source_id}"
        ),
        "title_jpn": meta.get("title_jpn") or meta.get("title_original") or "",
        "category": meta.get("category") or meta.get("type", ""),
        "language": meta.get("lang") or meta.get("language", ""),
        "pages": page_count,
        "posted_at": posted_at,
        "uploader": meta.get("uploader", ""),
        "download_status": "complete",
        "metadata_updated_at": func.now(),
        "tags_array": tags,
        "artist_id": artist_id,
    }


async def local_import_job(ctx: dict, source_dir: str, mode: str, gallery_id: int) -> dict:
    """Import a local directory into the database with progress tracking."""
    import json as _json

    logger.info("[local_import] gallery_id=%d source=%s mode=%s", gallery_id, source_dir, mode)

    src_path = Path(source_dir)
    if not src_path.is_dir():
        return {"status": "failed", "error": f"not a directory: {source_dir}"}
    source_identity = SourceDirectoryIdentity.capture(src_path) if mode == "link" else None

    files_raw = [f for f in src_path.iterdir() if f.is_file() and f.suffix.lower() in _MEDIA_EXTS]
    # Validate magic bytes for image files; pass video files through without magic check
    files_validated = []
    skipped_magic = 0
    for f in files_raw:
        if f.suffix.lower() in _VIDEO_EXTS or _validate_image_magic(f):
            files_validated.append(f)
        else:
            skipped_magic += 1
    if skipped_magic:
        logger.warning(
            "[local_import] gallery_id=%d: skipped %d file(s) with invalid magic bytes", gallery_id, skipped_magic
        )
    files = sorted(files_validated, key=_natural_sort_key)

    if not files:
        return {"status": "failed", "error": "no supported files found"}

    total = len(files)
    processed = 0  # actual new Image rows inserted (used for gallery.pages)
    attempted = 0  # files attempted regardless of conflict (used for progress display)
    import_failures: list[dict[str, str]] = []
    terminal_status = "failed"
    final_pages = 0
    existing_missing_thumb = False
    sidecar_payload = None
    r = ctx["redis"]

    # Load gallery to get source/source_id for library symlink creation
    async with AsyncSessionLocal() as _gallery_session:
        _gallery = await _gallery_session.get(Gallery, gallery_id)
        if not _gallery:
            logger.error("[local_import] gallery_id=%d not found in DB", gallery_id)
            return {"status": "failed", "error": "gallery not found"}
        if _gallery.deleted_at is not None:
            # HR-014: never mutate a trashed gallery. This job may have been
            # enqueued before the gallery was trashed, or raced with a
            # concurrent trash operation — treat it as a no-op.
            logger.warning("[local_import] gallery_id=%d is trashed, skipping import (no-op)", gallery_id)
            return {"status": "skipped_trashed", "gallery_id": gallery_id}
        gallery_source = _gallery.source
        gallery_source_id = _gallery.source_id

    # Load excluded blob hashes for this gallery before processing files
    async with AsyncSessionLocal() as _excl_session:
        excluded_rows = (
            (await _excl_session.execute(select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == gallery_id)))
            .scalars()
            .all()
        )
    excluded_set: set[str] = set(excluded_rows)

    try:
        async with AsyncSessionLocal() as session:
            existing_rows = (
                await session.execute(select(Image.page_num, Image.blob_sha256).where(Image.gallery_id == gallery_id))
            ).all()
            known_sha256s = {row.blob_sha256 for row in existing_rows}
            existing_page_by_sha = {row.blob_sha256: row.page_num for row in existing_rows}
            max_page = max((row.page_num for row in existing_rows), default=0)
            pending_link_symlinks: list[tuple[str, Blob, str]] = []
            # Link mode only: re-verified at the commit boundary below.
            file_identities: list[SourceFileIdentity] = []

            for f in files:
                if source_identity is not None:
                    source_identity.assert_unchanged(f"before:{f.name}")
                try:
                    # Link mode stores the path, so the sha256 and the bytes at
                    # that path must be pinned together: the directory check
                    # cannot see a file replaced under the same name.
                    sha256, file_identity = await asyncio.to_thread(hash_file_with_identity, f)
                except (FileNotFoundError, OSError) as exc:
                    if source_identity is not None:
                        source_identity.assert_unchanged(f"read:{f.name}")
                    logger.warning(
                        "[local_import] gallery_id=%d: skipping deleted file %s: %s", gallery_id, f.name, exc
                    )
                    import_failures.append(
                        {
                            "filename": f.name,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                    attempted += 1
                    continue
                except SourceFileChangedError as exc:
                    # Recording sha(old bytes) against a path now holding new
                    # bytes is worse than skipping the file; the next rescan
                    # picks up whatever settled.
                    logger.warning("[local_import] gallery_id=%d: skipping %s — %s", gallery_id, f.name, exc)
                    import_failures.append({"filename": f.name, "error_type": type(exc).__name__, "error": str(exc)})
                    attempted += 1
                    continue
                if source_identity is not None:
                    source_identity.assert_unchanged(f"after:{f.name}")
                if mode == "link":
                    file_identities.append(file_identity)

                if sha256 in excluded_set:
                    logger.debug("[local_import] gallery_id=%d: skipping excluded blob %s", gallery_id, sha256[:12])
                    continue
                if sha256 in known_sha256s:
                    if not thumbnails_complete_at(thumb_dir(sha256)):
                        existing_missing_thumb = True
                        logger.debug(
                            "[local_import] gallery_id=%d: existing page %s missing thumbnail(s)",
                            gallery_id,
                            existing_page_by_sha.get(sha256),
                        )
                    attempted += 1
                    continue

                if mode == "copy":
                    # Hardlink/copy into CAS; create library symlink
                    blob = await store_blob(f, sha256, session)
                    image_external_path = None
                else:
                    # Link mode: record external path, do not copy file
                    image_external_path = str(f)
                    blob = await store_blob(
                        f,
                        sha256,
                        session,
                        storage="external",
                        external_path=image_external_path,
                    )

                # Flush blob upsert before inserting image (FK constraint)
                await session.flush()

                stmt = (
                    pg_insert(Image)
                    .values(
                        gallery_id=gallery_id,
                        page_num=max_page + 1,
                        filename=f.name,
                        blob_sha256=sha256,
                        external_path=image_external_path,
                        added_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing()
                    .returning(Image.id)
                )
                result = await session.execute(stmt)
                inserted = result.scalar_one_or_none()

                if inserted is not None:
                    # New Image row created — increment blob ref_count.
                    await increment_ref_count(sha256, session)
                    if image_external_path is None:
                        await create_library_symlink(gallery_source, gallery_source_id, f.name, blob)
                    else:
                        # Do not expose an external symlink until the pinned
                        # source identity passes the finalize boundary.
                        pending_link_symlinks.append((f.name, blob, image_external_path))
                    processed += 1
                    max_page += 1
                    known_sha256s.add(sha256)

                attempted += 1

                # Update progress every 5 files or proportionally for small batches
                update_every = max(1, min(5, total // 10))
                if attempted % update_every == 0 or attempted == total:
                    await r.setex(
                        f"import:progress:{gallery_id}",
                        3600,
                        _json.dumps({"processed": processed, "total": total, "status": "running"}),
                    )

            if source_identity is not None:
                source_identity.assert_unchanged("finalize")
                # Per-file re-check: the directory may be untouched while an
                # individual file was rewritten or swapped since we hashed it.
                for identity in file_identities:
                    identity.assert_unchanged("finalize")
                link_states: list[tuple[Path, str | None]] = []
                try:
                    for filename, blob, external_path in pending_link_symlinks:
                        link = library_dir(gallery_source, gallery_source_id) / filename
                        if link.exists() and not link.is_symlink():
                            raise FileExistsError(f"refusing to replace non-symlink library file: {link}")
                        previous_target = os.readlink(link) if link.is_symlink() else None
                        link_states.append((link, previous_target))
                        await create_library_symlink(
                            gallery_source,
                            gallery_source_id,
                            filename,
                            blob,
                            external_path=external_path,
                        )
                    source_identity.assert_unchanged("commit")
                    for identity in file_identities:
                        identity.assert_unchanged("commit")
                except Exception:
                    _restore_library_links(link_states)
                    raise

            # Update gallery page count and status
            gallery = await session.get(Gallery, gallery_id)
            if gallery:
                image_count = (
                    await session.execute(select(func.count(Image.id)).where(Image.gallery_id == gallery_id))
                ).scalar_one()
                final_pages = image_count
                gallery.pages = image_count
                if import_failures and attempted == len(import_failures):
                    terminal_status = "failed"
                elif import_failures:
                    terminal_status = "partial"
                else:
                    terminal_status = "complete"
                gallery.download_status = terminal_status
                if mode == "link" and not gallery.source_path:
                    gallery.source_path = (
                        source_identity.real_path if source_identity is not None else os.path.realpath(src_path)
                    )
                gallery.metadata_updated_at = func.now()
                # Capture before commit: attributes expire on commit
                sidecar_payload = sidecar_payload_from_gallery(gallery)

            await session.commit()
    except (SourceDirectoryChangedError, SourceFileChangedError) as exc:
        # Same remedy either way: the source moved under us, so keep whatever
        # was already committed and mark the gallery partial rather than
        # recording rows that describe bytes no longer at those paths.
        logger.warning("[local_import] gallery_id=%d aborted: %s", gallery_id, exc)
        async with AsyncSessionLocal() as status_session:
            gallery = await status_session.get(Gallery, gallery_id)
            existing_count = 0
            if gallery is not None and gallery.deleted_at is None:
                existing_count = (
                    await status_session.execute(select(func.count(Image.id)).where(Image.gallery_id == gallery_id))
                ).scalar_one()
                gallery.pages = existing_count
                gallery.download_status = "partial" if existing_count else "failed"
                gallery.metadata_updated_at = func.now()
                await status_session.commit()
        payload = {
            "processed": 0,
            "total": total,
            "status": "source_changed",
            "error": str(exc),
            "resumable": True,
        }
        await r.setex(f"import:progress:{gallery_id}", 3600, _json.dumps(payload))
        from core.events import EventType, emit_safe

        await emit_safe(
            EventType.IMPORT_FAILED,
            resource_type="gallery",
            resource_id=gallery_id,
            source="local",
            reason="source_changed",
            error=str(exc),
        )
        return payload
    except Exception as exc:
        # HR-019: any other in-process failure (LibraryDirCollisionError, an
        # OSError while hashing or symlinking) must still leave a terminal
        # status. A gallery stuck on `importing` is invisible to every later
        # scan path: auto_discover_job skips existing source_ids and
        # rescan_library_job only rewrites pages when it removed an image.
        #
        # This cannot cover the SIGKILL case that stranded four galleries on
        # 2026-08-13 — Python never runs then. That is what the startup sweeper
        # in worker/import_recovery.py is for; the two are not alternatives.
        logger.exception("[local_import] gallery_id=%d failed: %s", gallery_id, exc)
        async with AsyncSessionLocal() as status_session:
            gallery = await status_session.get(Gallery, gallery_id)
            if gallery is not None and gallery.deleted_at is None:
                existing_count = (
                    await status_session.execute(select(func.count(Image.id)).where(Image.gallery_id == gallery_id))
                ).scalar_one()
                gallery.pages = existing_count
                gallery.download_status = "partial" if existing_count else "failed"
                gallery.metadata_updated_at = func.now()
                await status_session.commit()
        # Re-raise so SAQ still records the job as failed; only the DB state
        # left behind changes.
        raise

    # Disaster-recovery sidecar (best-effort)
    if sidecar_payload is not None:
        await write_gallery_sidecar(gallery_source, gallery_source_id, sidecar_payload)

    # Write done state with short TTL so frontend can display completion
    await r.setex(
        f"import:progress:{gallery_id}",
        30,
        _json.dumps(
            {
                "processed": processed,
                "total": total,
                "status": "done" if terminal_status == "complete" else terminal_status,
                "import_failures": import_failures[:10],
            }
        ),
    )

    logger.info("[local_import] gallery_id=%d: %d files imported", gallery_id, processed)

    # Only new/changed imports need thumbnail work. Replayed local-import jobs for an
    # already complete gallery should not create duplicate render backlog.
    if processed > 0 or existing_missing_thumb:
        await core.queue.enqueue(
            "cover_thumbnail_job",
            gallery_id=gallery_id,
            _timeout=300,
            _job_id=f"cover-thumbnail:{gallery_id}",
        )
        await core.queue.enqueue(
            "thumbnail_job",
            gallery_id=gallery_id,
            _timeout=3600,
            _job_id=f"thumbnail:{gallery_id}",
        )

    # Trigger AI tagging if enabled
    if settings.tag_model_enabled:
        await core.queue.enqueue("tag_job", gallery_id=gallery_id)

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.IMPORT_COMPLETED, resource_type="gallery", resource_id=gallery_id, pages=final_pages, source="local"
    )

    return {
        "status": "done" if terminal_status == "complete" else terminal_status,
        "processed": processed,
        "import_failures": import_failures,
    }


async def batch_import_job(
    ctx: dict, root_dir: str, mode: str, galleries: list[dict], batch_id: str, user_id: int | None = None
) -> dict:
    """Batch import multiple galleries from a root directory."""
    import json as _json

    r = ctx["redis"]
    total = len(galleries)
    completed = 0
    failed = 0
    conflicts = 0
    raw_conflict_mode = await r.get("setting:import_conflict_mode")
    if isinstance(raw_conflict_mode, bytes):
        raw_conflict_mode = raw_conflict_mode.decode()
    conflict_mode = raw_conflict_mode or "manual"

    for entry in galleries:
        abs_path = entry["path"]
        artist = entry.get("artist")
        title = entry.get("title", Path(abs_path).name)

        # Use relative path as source_id to avoid collisions
        rel_path = os.path.relpath(abs_path, root_dir)

        try:
            async with AsyncSessionLocal() as session:
                existing = (
                    await session.execute(
                        select(Gallery).where(
                            Gallery.source == "local",
                            Gallery.source_id == rel_path,
                            Gallery.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None and conflict_mode == "manual":
                    session.add(
                        ImportConflict(
                            user_id=user_id,
                            existing_gallery_id=existing.id,
                            source="local",
                            source_id=rel_path,
                            incoming_payload={
                                "path": abs_path,
                                "root_dir": root_dir,
                                "mode": mode,
                                "title": title,
                                "artist": artist,
                            },
                        )
                    )
                    await session.commit()
                    conflicts += 1
                    continue
                if existing is not None:
                    gallery_id = existing.id
                    existing.title = title
                else:
                    result = await session.execute(
                        text(
                            "INSERT INTO galleries "
                            "(source, source_id, title, import_mode, library_path, source_path, artist_id, uploader, created_by_user_id)"
                            " VALUES (:source, :source_id, :title, :mode, :library_path, :source_path, :artist_id, :uploader, :user_id) "
                            "RETURNING id"
                        ),
                        {
                            "source": "local",
                            "source_id": rel_path,
                            "title": title,
                            "mode": mode,
                            "library_path": root_dir if mode == "link" else None,
                            "source_path": os.path.realpath(abs_path) if mode == "link" else None,
                            "artist_id": f"local:{artist}" if artist else None,
                            "uploader": artist,
                            "user_id": user_id,
                        },
                    )
                    gallery_id = result.scalar_one()
                await session.commit()

            # Update progress with current gallery
            await r.setex(
                f"import:batch:{batch_id}",
                3600,
                _json.dumps(
                    {
                        "total": total,
                        "completed": completed,
                        "failed": failed,
                        "conflicts": conflicts,
                        "status": "running",
                        "current_gallery_id": gallery_id,
                    }
                ),
            )

            # Directly call local_import_job logic. Partial/source-changed
            # results remain resumable but are not counted as completed.
            import_result = await local_import_job(ctx, abs_path, mode, gallery_id)
            if import_result.get("status") == "done":
                completed += 1
            else:
                failed += 1

        except Exception as e:
            logger.error("[batch_import] failed for %s: %s", abs_path, e)
            failed += 1

        # Update progress after each gallery
        await r.setex(
            f"import:batch:{batch_id}",
            3600,
            _json.dumps(
                {
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                    "conflicts": conflicts,
                    "status": "running",
                    "current_gallery_id": None,
                }
            ),
        )

    # Final status
    await r.setex(
        f"import:batch:{batch_id}",
        300,
        _json.dumps(
            {
                "total": total,
                "completed": completed,
                "failed": failed,
                "conflicts": conflicts,
                "status": "done",
                "current_gallery_id": None,
            }
        ),
    )

    logger.info(
        "[batch_import] batch_id=%s: %d completed, %d failed, %d conflicts",
        batch_id,
        completed,
        failed,
        conflicts,
    )

    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.IMPORT_COMPLETED,
        resource_type="system",
        completed=completed,
        failed=failed,
        conflicts=conflicts,
        batch_id=batch_id,
    )

    return {"status": "done", "completed": completed, "failed": failed, "conflicts": conflicts}
