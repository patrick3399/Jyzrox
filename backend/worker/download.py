"""Download job for the worker package."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from core.config import settings
from core.redis_client import DownloadSemaphore
from services.credential import get_credential
from worker.constants import logger
from worker.helpers import _set_job_progress, _set_job_status


async def download_job(
    ctx: dict,
    url: str,
    source: str = "",
    options: dict | None = None,
    db_job_id: str | None = None,
    total: int | None = None,
) -> dict:
    """Download a gallery via the plugin registry, falling back to gallery-dl."""
    logger.info("[download] url=%s", url)

    await _set_job_status(db_job_id, "running")
    started_at = datetime.now(UTC)

    from plugins.registry import plugin_registry
    from services.credential import list_credentials as _list_creds

    # Find the plugin that handles this URL
    plugin = await plugin_registry.get_handler(url)
    if not plugin:
        plugin = plugin_registry.get_fallback()
    if not plugin:
        err = "No plugin can handle this URL"
        logger.error("[download] %s", err)
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    source_id = plugin.meta.source_id

    # Load credentials
    if source_id == "gallery_dl":
        # gallery-dl needs ALL credentials to build its config file
        all_creds = await _list_creds()
        credentials: dict | str | None = {}
        for c in all_creds:
            val = await get_credential(c["source"])
            if val:
                credentials[c["source"]] = val  # type: ignore[index]
    else:
        credentials = await get_credential(source_id)

    # Determine output directory via Downloadable protocol — always use the
    # original plugin's resolver so files land in the right source-specific
    # subdirectory (e.g. /data/gallery/pixiv/12345) even when we later swap
    # the executor to the gallery-dl fallback.
    downloader = plugin_registry.get_downloader(source_id)
    if downloader:
        target_dir = downloader.resolve_output_dir(url, Path(settings.data_gallery_path))
    else:
        target_dir = Path(settings.data_gallery_path) / (db_job_id or "local_test")

    # Credential gate — generic via Downloadable protocol.
    if downloader and downloader.requires_credentials() and not credentials:
        err = f"{plugin.meta.name} credentials not configured. Go to Credentials to set up."
        logger.error("[download] %s", err)
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    # Semaphore — use source_id as the semaphore key (maps to existing keys)
    sem_key = plugin.meta.semaphore_key or source_id
    if sem_key == "gallery_dl":
        domain = urlparse(url).netloc.removeprefix("www.")
        sem_key = f"gallery_dl:{domain}"
    limit = await DownloadSemaphore.get_limit(sem_key)
    sem = DownloadSemaphore(sem_key, max_count=limit)
    _base_progress: dict = {} if total is None else {"total": total}
    await _set_job_progress(db_job_id, {**_base_progress, "status_text": "Waiting for download slot..."})

    # Progress callback
    async def on_progress(downloaded: int, total_pages: int) -> None:
        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        speed = round(downloaded / elapsed, 3) if elapsed > 0 else 0
        status_text = (
            f"Downloading... ({downloaded}/{total_pages})" if total_pages > 0 else "Downloading..."
        )
        progress: dict = {
            **_base_progress,
            **({"total": total_pages} if total_pages > 0 else {}),
            "downloaded": downloaded,
            "started_at": started_at.isoformat(),
            "last_update_at": datetime.now(UTC).isoformat(),
            "speed": speed,
            "status_text": status_text,
        }
        # Preserve title / gallery_id set by the on_file callback
        if importer is not None:
            if importer.title:
                progress["title"] = importer.title
            if importer.gallery_id:
                progress["gallery_id"] = importer.gallery_id
        await _set_job_progress(db_job_id, progress)

    # Cancel check — reads the Redis cancel key set by the cancel endpoint
    redis = ctx["redis"]
    cancel_key = f"download:cancel:{db_job_id}" if db_job_id else None

    async def cancel_check() -> bool:
        if not cancel_key:
            return False
        try:
            val = await redis.get(cancel_key)
            return val is not None
        except Exception:
            return False

    # PID callback for gallery-dl pause/resume
    pid_key = f"download:pid:{db_job_id}" if db_job_id else None

    async def pid_callback(pid: int) -> None:
        if pid_key:
            try:
                await redis.set(pid_key, pid, ex=3600)
            except Exception as exc:
                logger.warning("[download] failed to store PID in Redis: %s", exc)

    # Pause check — reads the Redis pause key set by the pause endpoint (EH/Pixiv soft-pause)
    pause_key = f"download:pause:{db_job_id}" if db_job_id else None

    async def pause_check() -> bool:
        if not pause_key:
            return False
        try:
            val = await redis.get(pause_key)
            return val is not None
        except Exception:
            return False

    from worker.progressive import ProgressiveImporter
    from worker.constants import _MEDIA_EXTS

    importer: ProgressiveImporter | None = None

    if source_id == "gallery_dl":
        # Look up user_id from the download job
        import_user_id = None
        if db_job_id:
            from core.database import AsyncSessionLocal
            from sqlalchemy.sql import select as sa_select
            from db.models import DownloadJob as _DJ
            async with AsyncSessionLocal() as _sess:
                _result = await _sess.execute(
                    sa_select(_DJ.user_id).where(_DJ.id == db_job_id)
                )
                import_user_id = _result.scalar_one_or_none()

        importer = ProgressiveImporter(db_job_id, import_user_id)
        importer.source_url = url

        async def on_file(file_path: Path):
            # Skip non-media files (metadata json, tags, etc.)
            if file_path.suffix.lower() not in _MEDIA_EXTS:
                return
            # First media file → look for per-image metadata JSON on disk
            if not importer.gallery_id:
                meta_path = Path(str(file_path) + ".json")
                if meta_path.exists():
                    try:
                        raw = json.loads(meta_path.read_text(encoding="utf-8"))
                        await importer.ensure_gallery(raw, target_dir)
                    except Exception as exc:
                        logger.warning("[download] failed to parse metadata: %s", exc)
                # Fallback: no metadata JSON available → create from URL
                if not importer.gallery_id:
                    try:
                        await importer.ensure_gallery_from_url(url, target_dir)
                    except Exception as exc:
                        logger.warning("[download] failed to create gallery from URL: %s", exc)
                        return
                # Update progress with title and gallery_id
                if importer.gallery_id:
                    await _set_job_progress(db_job_id, {
                        **_base_progress,
                        "title": importer.title,
                        "gallery_id": importer.gallery_id,
                        "status_text": f"Downloading: {importer.title}",
                    })
            await importer.import_file(file_path)

        plugin.set_file_callback(on_file)

    # Pass download options to plugin
    if hasattr(plugin, "set_options"):
        plugin.set_options(options)

    try:
        async with sem.acquire():
            try:
                result = await plugin.download(
                    url=url,
                    dest_dir=target_dir,
                    credentials=credentials,
                    on_progress=on_progress,
                    cancel_check=cancel_check,
                    pid_callback=pid_callback,
                    pause_check=pause_check,
                )
            except Exception as exc:
                err = f"Download failed: {exc}"
                logger.error("[download] %s", err, exc_info=True)
                if importer:
                    await importer.abort()
                await _set_job_status(db_job_id, "failed", err)
                return {"status": "failed", "error": err}
            finally:
                if pid_key:
                    try:
                        await redis.delete(pid_key)
                    except Exception:
                        pass
                if source_id == "gallery_dl" and hasattr(plugin, "set_file_callback"):
                    plugin.set_file_callback(None)
                if hasattr(plugin, "set_options"):
                    plugin.set_options(None)
    except TimeoutError:
        err = "No download slot available — timed out waiting. Please try again later."
        logger.error("[download] %s", err)
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    if result.status == "cancelled":
        if importer:
            await importer.abort()
        await _set_job_status(db_job_id, "cancelled")
        return {"status": "cancelled"}

    if result.status == "failed":
        if importer:
            await importer.abort()
        err = result.error or "Download failed"
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    # ── Image validation + partial detection ────────────────────────
    from worker.helpers import _validate_image_magic
    from worker.constants import _IMAGE_EXTS

    corrupt_pages: list[int] = []
    if target_dir.exists():
        for f in sorted(target_dir.iterdir()):
            if f.suffix.lower() in _IMAGE_EXTS and f.is_file():
                if not _validate_image_magic(f):
                    # Extract page number from filename (e.g. "0001.jpg" → 1)
                    try:
                        page_num = int(f.stem.lstrip("0") or "0")
                    except ValueError:
                        page_num = 0
                    corrupt_pages.append(page_num)
                    logger.warning("[download] corrupt image removed: %s", f.name)
                    f.unlink(missing_ok=True)

    all_failed = sorted(set(getattr(result, 'failed_pages', []) + corrupt_pages))

    # Final progress update
    elapsed = (datetime.now(UTC) - started_at).total_seconds()
    speed = round(result.downloaded / elapsed, 3) if elapsed > 0 else 0
    final_progress = {
        **_base_progress,
        "total": result.total or result.downloaded,
        "downloaded": result.downloaded,
        "started_at": started_at.isoformat(),
        "last_update_at": datetime.now(UTC).isoformat(),
        "speed": speed,
        "status_text": "Complete" if not all_failed else f"Partial — {len(all_failed)} pages failed",
    }
    # Preserve title / gallery_id set by the on_file callback
    if importer is not None:
        if importer.title:
            final_progress["title"] = importer.title
        if importer.gallery_id:
            final_progress["gallery_id"] = importer.gallery_id
    if all_failed:
        final_progress["failed_pages"] = all_failed
    await _set_job_progress(db_job_id, final_progress)

    # Trigger import regardless (partial pages are still useful)
    if target_dir.exists():
        if importer and importer.gallery_id:
            # Progressive import was active — finalize instead of running import_job
            gallery_id = await importer.finalize(target_dir, partial=bool(all_failed))
            logger.info("[download] progressive import finalized: gallery_id=%s", gallery_id)
            # Skip import_job and thumbnail_job — already done progressively
        else:
            # Fallback: no progressive import, use existing import_job
            import_user_id = None
            if db_job_id:
                from core.database import AsyncSessionLocal
                from sqlalchemy.sql import select as sa_select
                from db.models import DownloadJob
                async with AsyncSessionLocal() as session:
                    _result = await session.execute(
                        sa_select(DownloadJob.user_id).where(DownloadJob.id == db_job_id)
                    )
                    import_user_id = _result.scalar_one_or_none()
            await ctx["redis"].enqueue_job("import_job", str(target_dir), db_job_id, import_user_id, url)

    if all_failed:
        await _set_job_status(db_job_id, "partial")
        logger.warning("[download] partial: %d pages failed: %s", len(all_failed), all_failed)
        return {"status": "partial", "downloaded": result.downloaded, "failed_pages": all_failed}

    await _set_job_status(db_job_id, "done")
    logger.info("[download] done: %s (downloaded=%d)", url, result.downloaded)
    return {"status": "done", "downloaded": result.downloaded}
