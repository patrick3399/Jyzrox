"""Import jobs for the worker package."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import core.queue

from collections import Counter

from sqlalchemy import func, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

from core.config import settings
from core.database import AsyncSessionLocal
from db.models import Blob, ExcludedBlob, Gallery, GalleryTag, Image, Tag
from services.cas import create_library_symlink, store_blob
from worker.constants import (
    _IMAGE_EXTS,
    _MEDIA_EXTS,
    _VIDEO_EXTS,
    logger,
)
from worker.helpers import _sha256, _validate_image_magic
from worker.tag_helpers import rebuild_gallery_tags_array, upsert_tag_translations


async def import_job(ctx: dict, path: str, db_job_id: str | None = None, user_id: int | None = None, source_url: str | None = None) -> dict:
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
    media_files_raw = [f for f in gallery_path.rglob('*') if f.is_file() and f.suffix.lower() in _MEDIA_EXTS]
    # Validate magic bytes for images; pass video files through without check
    media_files = []
    skipped = 0
    for f in media_files_raw:
        if f.suffix.lower() in _VIDEO_EXTS:
            media_files.append(f)
        elif _validate_image_magic(f):
            media_files.append(f)
        else:
            skipped += 1
    media_files.sort(key=lambda f: f.name)
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
                "pages": len(media_files),
                "posted_at": import_data.posted_at,
                "uploader": import_data.uploader,
                "download_status": "complete",
                "metadata_updated_at": func.now(),
                "tags_array": import_data.tags,
                "artist_id": import_data.artist_id,
                "created_by_user_id": user_id,
                "source_url": source_url,
            }
            tags = import_data.tags
            source_id = import_data.source_id
        else:
            gallery_values = _build_gallery(source, source_id, metadata, tags, len(media_files))
            gallery_values["created_by_user_id"] = user_id
            gallery_values["source_url"] = source_url
        stmt = (
            pg_insert(Gallery)
            .values(**gallery_values)
            .on_conflict_do_update(
                index_elements=["source", "source_id"],
                set_={
                    "title": pg_insert(Gallery).excluded.title,
                    "tags_array": pg_insert(Gallery).excluded.tags_array,
                    "download_status": "complete",
                    "metadata_updated_at": func.now(),
                    "pages": pg_insert(Gallery).excluded.pages,
                    "artist_id": pg_insert(Gallery).excluded.artist_id,
                    "source_url": pg_insert(Gallery).excluded.source_url,
                },
            )
            .returning(Gallery.id)
        )
        gallery_id = (await session.execute(stmt)).scalar_one()

        # Load excluded blob hashes for this gallery
        excluded_rows = (await session.execute(
            select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == gallery_id)
        )).scalars().all()
        excluded_set: set[str] = set(excluded_rows)

        # Compute hashes with bounded concurrency to avoid thread pool exhaustion
        _hash_sem = asyncio.Semaphore(10)

        async def _sha256_limited(f):
            async with _hash_sem:
                return await asyncio.to_thread(_sha256, f)

        hashes = await asyncio.gather(*[_sha256_limited(f) for f in media_files])

        # Filter out files whose sha256 is in the excluded set
        allowed_pairs = [
            (img_file, sha256)
            for img_file, sha256 in zip(media_files, hashes, strict=False)
            if sha256 not in excluded_set
        ]
        if len(allowed_pairs) < len(media_files):
            logger.info(
                "[import] gallery_id=%d: skipped %d excluded blob(s)",
                gallery_id,
                len(media_files) - len(allowed_pairs),
            )

        # Store each file in CAS and create library symlink
        for img_file, sha256 in allowed_pairs:
            blob = await store_blob(img_file, sha256, session)
            await create_library_symlink(source, source_id, img_file.name, blob)

        # Flush blob upserts before inserting images (FK: blob_sha256 → blobs.sha256)
        await session.flush()

        # Bulk-insert images
        now = datetime.now(UTC)
        image_values = [
            {
                "gallery_id": gallery_id,
                "page_num": page_num,
                "filename": img_file.name,
                "blob_sha256": sha256,
                "added_at": now,
            }
            for page_num, (img_file, sha256) in enumerate(allowed_pairs, start=1)
        ]
        if image_values:
            img_stmt = (
                pg_insert(Image)
                .values(image_values)
                .on_conflict_do_nothing()
                .returning(Image.id, Image.blob_sha256)
            )
            result = await session.execute(img_stmt)
            inserted_rows = result.all()

            if inserted_rows:
                # Only increment ref_count for blobs that got a new Image row.
                sha_counts = Counter(row.blob_sha256 for row in inserted_rows)
                for sha, count in sha_counts.items():
                    await session.execute(
                        update(Blob)
                        .where(Blob.sha256 == sha)
                        .values(ref_count=Blob.ref_count + count)
                    )

        # Upsert tags + gallery_tags
        await _upsert_tags(session, gallery_id, tags)

        # Upsert tag translations if present in metadata
        tag_translations = metadata.get("tag_translations")
        if tag_translations:
            await upsert_tag_translations(session, tag_translations)

        # Rebuild tags_array from gallery_tags (single source of truth)
        await rebuild_gallery_tags_array(session, gallery_id)

        await session.commit()

    # Delete the temporary download directory
    try:
        _shutil.rmtree(str(gallery_path), ignore_errors=True)
    except Exception as exc:
        logger.warning("[import] failed to remove temp dir %s: %s", gallery_path, exc)

    logger.info("[import] gallery_id=%d source=%s/%s", gallery_id, source, source_id)

    # Trigger thumbnail generation
    await core.queue.enqueue("thumbnail_job", gallery_id=gallery_id)
    if settings.tag_model_enabled:
        await core.queue.enqueue("tag_job", gallery_id=gallery_id)

    from core.events import EventType, emit_safe
    await emit_safe(EventType.IMPORT_COMPLETED, resource_type="gallery", resource_id=gallery_id, pages=len(allowed_pairs), source=source)

    return {"status": "done", "gallery_id": gallery_id}


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


async def _upsert_tags(session, gallery_id: int, tags: list[str]) -> None:
    if not tags:
        return

    # Step 1: deduplicate so we don't send duplicate rows to the DB
    seen: set[tuple[str, str]] = set()
    tag_values: list[dict] = []
    for tag_str in tags:
        if ":" in tag_str:
            ns, name = tag_str.split(":", 1)
        else:
            ns, name = "general", tag_str
        key = (ns, name)
        if key not in seen:
            seen.add(key)
            tag_values.append({"namespace": ns, "name": name, "count": 1})

    # Step 2: batch upsert all tags, retrieve their IDs in a single round-trip
    tag_stmt = (
        pg_insert(Tag)
        .values(tag_values)
        .on_conflict_do_update(
            index_elements=["namespace", "name"],
            set_={"count": Tag.count + 1},
        )
        .returning(Tag.id)
    )
    tag_ids = (await session.execute(tag_stmt)).scalars().all()

    # Step 3: batch insert gallery_tag junction rows in a single round-trip
    gt_values = [{"gallery_id": gallery_id, "tag_id": tid, "confidence": 1.0, "source": "metadata"} for tid in tag_ids]
    if gt_values:
        gt_stmt = pg_insert(GalleryTag).values(gt_values).on_conflict_do_nothing()
        await session.execute(gt_stmt)


async def local_import_job(ctx: dict, source_dir: str, mode: str, gallery_id: int) -> dict:
    """Import a local directory into the database with progress tracking."""
    import json as _json

    logger.info("[local_import] gallery_id=%d source=%s mode=%s", gallery_id, source_dir, mode)

    src_path = Path(source_dir)
    if not src_path.is_dir():
        return {"status": "failed", "error": f"not a directory: {source_dir}"}

    _SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".mp4", ".webm"}
    _VIDEO_EXTS = {".mp4", ".webm"}
    files_raw = [f for f in src_path.iterdir() if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS]
    # Validate magic bytes for image files; pass video files through without magic check
    files_validated = []
    skipped_magic = 0
    for f in files_raw:
        if f.suffix.lower() in _VIDEO_EXTS:
            files_validated.append(f)
        elif _validate_image_magic(f):
            files_validated.append(f)
        else:
            skipped_magic += 1
    if skipped_magic:
        logger.warning("[local_import] gallery_id=%d: skipped %d file(s) with invalid magic bytes", gallery_id, skipped_magic)
    files = sorted(files_validated)

    if not files:
        return {"status": "failed", "error": "no supported files found"}

    total = len(files)
    processed = 0   # actual new Image rows inserted (used for gallery.pages)
    attempted = 0   # files attempted regardless of conflict (used for progress display)
    r = ctx["redis"]

    # Load gallery to get source/source_id for library symlink creation
    async with AsyncSessionLocal() as _gallery_session:
        _gallery = await _gallery_session.get(Gallery, gallery_id)
        if not _gallery:
            logger.error("[local_import] gallery_id=%d not found in DB", gallery_id)
            return {"status": "failed", "error": "gallery not found"}
        gallery_source = _gallery.source
        gallery_source_id = _gallery.source_id

    # Load excluded blob hashes for this gallery before processing files
    async with AsyncSessionLocal() as _excl_session:
        excluded_rows = (await _excl_session.execute(
            select(ExcludedBlob.blob_sha256).where(ExcludedBlob.gallery_id == gallery_id)
        )).scalars().all()
    excluded_set: set[str] = set(excluded_rows)

    async with AsyncSessionLocal() as session:
        for idx, f in enumerate(files):
            sha256 = await asyncio.to_thread(_sha256, f)

            if sha256 in excluded_set:
                logger.debug("[local_import] gallery_id=%d: skipping excluded blob %s", gallery_id, sha256[:12])
                continue

            if mode == "copy":
                # Hardlink/copy into CAS; create library symlink
                blob = await store_blob(f, sha256, session)
            else:
                # Link mode: record external path, do not copy file
                blob = await store_blob(f, sha256, session, storage="external", external_path=str(f))

            await create_library_symlink(gallery_source, gallery_source_id, f.name, blob)

            # Flush blob upsert before inserting image (FK constraint)
            await session.flush()

            stmt = (
                pg_insert(Image)
                .values(
                    gallery_id=gallery_id,
                    page_num=idx + 1,
                    filename=f.name,
                    blob_sha256=sha256,
                    added_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing()
                .returning(Image.id)
            )
            result = await session.execute(stmt)
            inserted = result.scalar_one_or_none()

            if inserted is not None:
                # New Image row created — increment blob ref_count.
                await session.execute(
                    update(Blob)
                    .where(Blob.sha256 == sha256)
                    .values(ref_count=Blob.ref_count + 1)
                )
                processed += 1

            attempted += 1

            # Update progress every 5 files or proportionally for small batches
            update_every = max(1, min(5, total // 10))
            if attempted % update_every == 0 or attempted == total:
                await r.setex(
                    f"import:progress:{gallery_id}",
                    3600,
                    _json.dumps({"processed": processed, "total": total, "status": "running"}),
                )

        # Update gallery page count and status
        gallery = await session.get(Gallery, gallery_id)
        if gallery:
            gallery.pages = processed
            gallery.download_status = "complete"
            gallery.metadata_updated_at = func.now()

        await session.commit()

    # Write done state with short TTL so frontend can display completion
    await r.setex(
        f"import:progress:{gallery_id}",
        30,
        _json.dumps({"processed": processed, "total": total, "status": "done"}),
    )

    logger.info("[local_import] gallery_id=%d: %d files imported", gallery_id, processed)

    # Trigger thumbnail generation
    await core.queue.enqueue("thumbnail_job", gallery_id=gallery_id)

    # Trigger AI tagging if enabled
    if settings.tag_model_enabled:
        await core.queue.enqueue("tag_job", gallery_id=gallery_id)

    from core.events import EventType, emit_safe
    await emit_safe(EventType.IMPORT_COMPLETED, resource_type="gallery", resource_id=gallery_id, pages=processed, source="local")

    return {"status": "done", "processed": processed}


async def batch_import_job(ctx: dict, root_dir: str, mode: str, galleries: list[dict], batch_id: str, user_id: int | None = None) -> dict:
    """Batch import multiple galleries from a root directory."""
    import json as _json

    r = ctx["redis"]
    total = len(galleries)
    completed = 0
    failed = 0

    for entry in galleries:
        abs_path = entry["path"]
        artist = entry.get("artist")
        title = entry.get("title", Path(abs_path).name)

        # Use relative path as source_id to avoid collisions
        rel_path = os.path.relpath(abs_path, root_dir)

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    text(
                        "INSERT INTO galleries (source, source_id, title, import_mode, library_path, artist_id, created_by_user_id)"
                        " VALUES (:source, :source_id, :title, :mode, :library_path, :artist_id, :user_id) RETURNING id"
                    ),
                    {
                        "source": "local",
                        "source_id": rel_path,
                        "title": title,
                        "mode": mode,
                        "library_path": root_dir if mode == "link" else None,
                        "artist_id": f"local:{artist}" if artist else None,
                        "user_id": user_id,
                    },
                )
                gallery_id = result.scalar_one()
                await session.commit()

            # Update progress with current gallery
            await r.setex(
                f"import:batch:{batch_id}",
                3600,
                _json.dumps({
                    "total": total, "completed": completed, "failed": failed,
                    "status": "running", "current_gallery_id": gallery_id,
                }),
            )

            # Directly call local_import_job logic
            await local_import_job(ctx, abs_path, mode, gallery_id)
            completed += 1

        except Exception as e:
            logger.error("[batch_import] failed for %s: %s", abs_path, e)
            failed += 1

        # Update progress after each gallery
        await r.setex(
            f"import:batch:{batch_id}",
            3600,
            _json.dumps({
                "total": total, "completed": completed, "failed": failed,
                "status": "running", "current_gallery_id": None,
            }),
        )

    # Final status
    await r.setex(
        f"import:batch:{batch_id}",
        300,
        _json.dumps({
            "total": total, "completed": completed, "failed": failed,
            "status": "done", "current_gallery_id": None,
        }),
    )

    logger.info("[batch_import] batch_id=%s: %d completed, %d failed", batch_id, completed, failed)

    from core.events import EventType, emit_safe
    await emit_safe(EventType.IMPORT_COMPLETED, resource_type="system", completed=completed, failed=failed, batch_id=batch_id)

    return {"status": "done", "completed": completed, "failed": failed}
