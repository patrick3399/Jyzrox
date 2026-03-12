"""Download job for the worker package."""

from datetime import UTC, datetime
from pathlib import Path

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
    sem = DownloadSemaphore(sem_key)
    _base_progress: dict = {} if total is None else {"total": total}
    await _set_job_progress(db_job_id, {**_base_progress, "status_text": "Waiting for download slot..."})

    # Progress callback
    async def on_progress(downloaded: int, total_pages: int) -> None:
        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        speed = round(downloaded / elapsed, 3) if elapsed > 0 else 0
        status_text = (
            f"Downloading... ({downloaded}/{total_pages})" if total_pages > 0 else "Downloading..."
        )
        await _set_job_progress(db_job_id, {
            **_base_progress,
            **({"total": total_pages} if total_pages > 0 else {}),
            "downloaded": downloaded,
            "started_at": started_at.isoformat(),
            "last_update_at": datetime.now(UTC).isoformat(),
            "speed": speed,
            "status_text": status_text,
        })

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

    if result.status == "cancelled":
        await _set_job_status(db_job_id, "cancelled")
        return {"status": "cancelled"}

    if result.status == "failed":
        err = result.error or "Download failed"
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    # Final progress update
    elapsed = (datetime.now(UTC) - started_at).total_seconds()
    speed = round(result.downloaded / elapsed, 3) if elapsed > 0 else 0
    await _set_job_progress(db_job_id, {
        **_base_progress,
        "total": result.total or result.downloaded,
        "downloaded": result.downloaded,
        "started_at": started_at.isoformat(),
        "last_update_at": datetime.now(UTC).isoformat(),
        "speed": speed,
        "status_text": "Complete",
    })

    # Trigger import
    if target_dir.exists():
        await ctx["redis"].enqueue_job("import_job", str(target_dir), db_job_id)

    await _set_job_status(db_job_id, "done")

    if result.failed_pages:
        logger.warning("[download] %d pages failed: %s", len(result.failed_pages), result.failed_pages)

    logger.info("[download] done: %s (downloaded=%d)", url, result.downloaded)
    return {"status": "done", "downloaded": result.downloaded}
