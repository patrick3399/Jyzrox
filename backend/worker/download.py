"""Download job for the worker package."""

import asyncio
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
    """Download a gallery via the plugin registry — unified progressive import."""
    logger.info("[download] url=%s", url)

    await _set_job_status(db_job_id, "running")
    started_at = datetime.now(UTC)

    from plugins.registry import plugin_registry
    from services.credential import list_credentials as _list_creds

    # ── 1. Find plugin ──────────────────────────────────────────────
    plugin = await plugin_registry.get_handler(url)
    if not plugin:
        plugin = plugin_registry.get_fallback()
    if not plugin:
        err = "No plugin can handle this URL"
        logger.error("[download] %s", err)
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    source_id = plugin.meta.source_id

    # ── 2. Load credentials (unified) ───────────────────────────────
    if plugin.meta.needs_all_credentials:
        all_creds = await _list_creds()
        credentials: dict | str | None = {}
        for c in all_creds:
            val = await get_credential(c["source"])
            if val:
                credentials[c["source"]] = val  # type: ignore[index]
    else:
        credentials = await get_credential(source_id)

    # ── 3. Output directory ─────────────────────────────────────────
    downloader = plugin_registry.get_downloader(source_id)
    if downloader:
        target_dir = downloader.resolve_output_dir(url, Path(settings.data_gallery_path))
    else:
        target_dir = Path(settings.data_gallery_path) / (db_job_id or "local_test")

    # ── 4. Credential gate ──────────────────────────────────────────
    if downloader and downloader.requires_credentials() and not credentials:
        err = f"{plugin.meta.name} credentials not configured. Go to Credentials to set up."
        logger.error("[download] %s", err)
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    # ── 5. Semaphore ────────────────────────────────────────────────
    sem_key = plugin.meta.semaphore_key or source_id
    if sem_key == "gallery_dl":
        domain = urlparse(url).netloc.removeprefix("www.")
        sem_key = f"gallery_dl:{domain}"
    limit = await DownloadSemaphore.get_limit(sem_key)
    sem = DownloadSemaphore(sem_key, max_count=limit)
    _base_progress: dict = {} if total is None else {"total": total}
    await _set_job_progress(db_job_id, {**_base_progress, "status_text": "Waiting for download slot..."})

    # ── 6. Progressive Importer (ALL sources) ───────────────────────
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

    from worker.progressive import ProgressiveImporter
    from worker.constants import _MEDIA_EXTS

    # Use filename-based page numbering for plugins with parallel downloads
    page_from_filename = (plugin.meta.concurrency > 1)
    importer = ProgressiveImporter(db_job_id, import_user_id, page_num_from_filename=page_from_filename)
    importer.source_url = url

    # ── 7. Pre-download metadata (native plugins) ──────────────────
    if hasattr(plugin, 'resolve_metadata'):
        try:
            import_data = await plugin.resolve_metadata(url, credentials)
            if import_data:
                await importer.ensure_gallery_from_import_data(import_data)
                await _set_job_progress(db_job_id, {
                    **_base_progress,
                    "title": importer.title,
                    "gallery_id": importer.gallery_id,
                    "status_text": f"Downloading: {importer.title}",
                })
        except Exception as exc:
            logger.warning("[download] resolve_metadata failed (non-fatal): %s", exc)

    # ── 8. Progress callback ────────────────────────────────────────
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
        if importer.title:
            progress["title"] = importer.title
        if importer.gallery_id:
            progress["gallery_id"] = importer.gallery_id
        await _set_job_progress(db_job_id, progress)

    # ── 9. Cancel / Pause / PID callbacks ───────────────────────────
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

    pid_key = f"download:pid:{db_job_id}" if db_job_id else None

    async def pid_callback(pid: int) -> None:
        if pid_key:
            try:
                await redis.set(pid_key, pid, ex=3600)
            except Exception as exc:
                logger.warning("[download] failed to store PID in Redis: %s", exc)

    pause_key = f"download:pause:{db_job_id}" if db_job_id else None

    async def pause_check() -> bool:
        if not pause_key:
            return False
        try:
            val = await redis.get(pause_key)
            return val is not None
        except Exception:
            return False

    # ── 10. Unified on_file callback (ALL sources) ──────────────────
    _gallery_create_lock = asyncio.Lock()

    async def on_file(file_path: Path):
        if file_path.suffix.lower() not in _MEDIA_EXTS:
            return
        # Serialize gallery creation to avoid race with concurrent downloads
        if not importer.gallery_id:
            async with _gallery_create_lock:
                if not importer.gallery_id:  # double-check after acquiring lock
                    meta_path = Path(str(file_path) + ".json")
                    if meta_path.exists():
                        try:
                            raw = json.loads(meta_path.read_text(encoding="utf-8"))
                            await importer.ensure_gallery(raw, target_dir)
                        except Exception as exc:
                            logger.warning("[download] failed to parse metadata: %s", exc)
                    if not importer.gallery_id:
                        try:
                            await importer.ensure_gallery_from_url(url, target_dir)
                        except Exception as exc:
                            logger.warning("[download] failed to create gallery from URL: %s", exc)
                            return
                    if importer.gallery_id:
                        await _set_job_progress(db_job_id, {
                            **_base_progress,
                            "title": importer.title,
                            "gallery_id": importer.gallery_id,
                            "status_text": f"Downloading: {importer.title}",
                        })
        await importer.import_file(file_path)

    # ── 11. Execute download ────────────────────────────────────────
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
                    on_file=on_file,
                    **({"options": options} if options else {}),
                )
            except Exception as exc:
                err = f"Download failed: {exc}"
                logger.error("[download] %s", err, exc_info=True)
                await importer.abort()
                await _set_job_status(db_job_id, "failed", err)
                return {"status": "failed", "error": err}
            finally:
                if pid_key:
                    try:
                        await redis.delete(pid_key)
                    except Exception:
                        pass
    except TimeoutError:
        err = "No download slot available — timed out waiting. Please try again later."
        logger.error("[download] %s", err)
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    # ── 12. Post-download: cancel guard ─────────────────────────────
    if result.status == "cancelled":
        await importer.cleanup()
        await _set_job_status(db_job_id, "cancelled")
        return {"status": "cancelled"}

    if result.status == "failed":
        if result.downloaded > 0 and importer.gallery_id:
            logger.warning(
                "[download] treating failed download as partial (downloaded=%d): %s",
                result.downloaded,
                result.error,
            )
        else:
            await importer.abort()
            err = result.error or "Download failed"
            await _set_job_status(db_job_id, "failed", err)
            return {"status": "failed", "error": err}

    if await cancel_check():
        await importer.cleanup()
        await _set_job_status(db_job_id, "cancelled")
        logger.info("[download] cancelled (post-download guard): %s", url)
        return {"status": "cancelled"}

    # ── 13. Image validation ────────────────────────────────────────
    from worker.helpers import _validate_image_magic
    from worker.constants import _IMAGE_EXTS

    corrupt_pages: list[int] = []
    if target_dir.exists():
        for f in sorted(target_dir.rglob("*")):
            if f.suffix.lower() in _IMAGE_EXTS and f.is_file():
                if not _validate_image_magic(f):
                    try:
                        page_num = int(f.stem.lstrip("0") or "0")
                    except ValueError:
                        page_num = 0
                    corrupt_pages.append(page_num)
                    logger.warning("[download] corrupt image removed: %s", f.name)
                    f.unlink(missing_ok=True)

    all_failed = sorted(set(getattr(result, 'failed_pages', []) + corrupt_pages))

    # ── 14. Final progress update ───────────────────────────────────
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
    if importer.title:
        final_progress["title"] = importer.title
    if importer.gallery_id:
        final_progress["gallery_id"] = importer.gallery_id
    if all_failed:
        final_progress["failed_pages"] = all_failed
    await _set_job_progress(db_job_id, final_progress)

    # ── 15. Finalize ────────────────────────────────────────────────
    if target_dir.exists():
        if importer.gallery_id:
            gallery_id = await importer.finalize(target_dir, partial=bool(all_failed) or result.status in ("failed", "partial"))
            logger.info("[download] progressive import finalized: gallery_id=%s", gallery_id)
        else:
            # Safety fallback: no progressive import occurred (should be rare)
            await ctx["redis"].enqueue_job("import_job", str(target_dir), db_job_id, import_user_id, url)

    is_partial = bool(all_failed) or result.status in ("failed", "partial")
    if is_partial:
        if all_failed:
            partial_msg = f"Partial — {len(all_failed)} pages failed"
            if result.error:
                partial_msg = f"{partial_msg}; {result.error}"
        else:
            partial_msg = result.error or "Partial download"
        await _set_job_status(db_job_id, "partial", partial_msg)
        logger.warning(
            "[download] partial: downloaded=%d failed_pages=%s error=%s",
            result.downloaded,
            all_failed or [],
            result.error,
        )
        return {
            "status": "partial",
            "downloaded": result.downloaded,
            "failed_pages": all_failed,
            "error": result.error,
        }

    await _set_job_status(db_job_id, "done")
    logger.info("[download] done: %s (downloaded=%d)", url, result.downloaded)
    return {"status": "done", "downloaded": result.downloaded}
