"""Download job for the worker package."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from core.config import settings
from core.events import EventType, emit_safe
from core.redis_client import DownloadSemaphore
from services.credential import get_credential
from worker.constants import _IMAGE_EXTS, DISK_LOW_KEY, logger
from worker.helpers import _set_job_progress, _set_job_status, _validate_image_magic, check_disk_space


def _postprocess_failure_status(downloaded: int) -> str:
    """Never report a post-processing failure as a completed download."""
    return "partial" if downloaded > 0 else "failed"


async def _writeback_cookies(credentials: dict | str | None, job_id: str) -> None:
    """Read cookie update files written by gallery-dl's cookies-update PP and save to DB."""
    import http.cookiejar

    if not isinstance(credentials, dict):
        return

    from plugins.builtin.gallery_dl._sites import cookie_writeback_path, get_site_config
    from services.credential import set_credential

    for src in credentials:
        cfg = get_site_config(src)
        if cfg.credential_type != "cookies":
            continue
        cookie_path = Path(cookie_writeback_path(job_id, src))
        if not cookie_path.exists():
            continue
        try:
            jar = http.cookiejar.MozillaCookieJar(str(cookie_path))
            jar.load(ignore_discard=True, ignore_expires=True)
            updated = {c.name: c.value for c in jar}
            if updated:
                original_raw = credentials.get(src, "{}")
                try:
                    original = json.loads(original_raw) if isinstance(original_raw, str) else {}
                except json.JSONDecodeError, TypeError:
                    original = {}
                if updated != original:
                    await set_credential(src, json.dumps(updated), "cookies")
                    logger.info("[download] cookies updated for %s (%d cookies)", src, len(updated))
        except Exception as exc:
            logger.warning("[download] failed to update cookies for %s: %s", src, exc)
        finally:
            cookie_path.unlink(missing_ok=True)


async def _set_subscription_result(
    db_job_id: str | None,
    status: str,
    error: str | None = None,
    *,
    advance_success: bool = True,
) -> None:
    """Update subscription status after the associated download reaches a terminal state.

    advance_success=False suppresses the last_success_at update even when status="done".
    Use this when gallery-dl returned 0 downloaded + 0 skipped: the run produced no
    evidence the source was actually checked (date-after may have filtered everything),
    so advancing the cutoff would self-poison the next incremental check.
    """
    if not db_job_id:
        return
    try:
        from sqlalchemy import update

        from core.database import AsyncSessionLocal
        from db.models import DownloadJob, Subscription

        async with AsyncSessionLocal() as session:
            job = await session.get(DownloadJob, uuid.UUID(db_job_id))
            if not job or not job.subscription_id:
                return
            subscription_id = job.subscription_id
            values = {
                "last_status": status,
                "last_error": error[:500] if error else None,
            }
            if status == "done" and advance_success:
                values["last_success_at"] = datetime.now(UTC)
            await session.execute(update(Subscription).where(Subscription.id == subscription_id).values(**values))
            await session.commit()

        # DL-007: track consecutive failures (alert + backoff for chronic ones)
        from services.subscription_health import record_check_result

        await record_check_result(subscription_id, status)
    except Exception as exc:
        logger.warning("[download] failed to update subscription result: %s", exc)


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
        await _set_subscription_result(db_job_id, "failed", err)
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
        target_dir = downloader.resolve_output_dir(url, Path(settings.data_gallery_path), db_job_id)
    else:
        target_dir = Path(settings.data_gallery_path) / (db_job_id or "local_test")

    # ── 4. Credential gate ──────────────────────────────────────────
    if downloader and downloader.requires_credentials() and not credentials:
        err = f"{plugin.meta.name} credentials not configured. Go to Credentials to set up."
        logger.error("[download] %s", err)
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    # ── 4b. Disk space pre-flight ─────────────────────────────────────
    # Fast path: check the Redis flag set by disk_monitor_job (no syscall).
    # Fall back to a direct check if the flag was never set (e.g. first boot).
    redis = ctx["redis"]
    disk_low_val = await redis.get(DISK_LOW_KEY)
    if disk_low_val is not None:
        _free = disk_low_val.decode() if isinstance(disk_low_val, bytes) else disk_low_val
        disk_ok, free_gb = False, float(_free)
    else:
        disk_ok, free_gb = check_disk_space("/data", settings.disk_min_free_gb)

    if not disk_ok:
        err = f"Insufficient disk space: {free_gb:.1f} GB free, {settings.disk_min_free_gb} GB required"
        logger.error("[download] %s", err)
        await _set_job_status(db_job_id, "failed", err)
        await emit_safe(EventType.SYSTEM_DISK_LOW, free_gb=free_gb)
        return {"status": "failed", "error": err}

    # ── 5. Semaphore ────────────────────────────────────────────────
    from core.site_config import site_config_service

    sem_key = plugin.meta.semaphore_key or source_id
    if source_id == "gallery_dl":
        from plugins.builtin.gallery_dl._sites import get_site_by_domain as _get_site_by_domain

        _url_domain = urlparse(url).netloc.removeprefix("www.")
        _url_source_id = _get_site_by_domain(_url_domain).source_id
        _dl_params = await site_config_service.get_effective_download_params(_url_source_id)
    else:
        _dl_params = await site_config_service.get_effective_download_params(source_id)

    if sem_key == "gallery_dl":
        domain = urlparse(url).netloc.removeprefix("www.")
        sem_key = f"gallery_dl:{domain}"
    sem = DownloadSemaphore(sem_key, max_count=_dl_params.concurrency)
    _base_progress: dict = {} if total is None else {"total": total}
    await _set_job_progress(db_job_id, {**_base_progress, "status_text": "Waiting for download slot..."})

    # ── 6. Progressive Importer (ALL sources) ───────────────────────
    import_user_id = None
    existing_gallery_id = None
    if db_job_id:
        from sqlalchemy.sql import select as sa_select

        from core.database import AsyncSessionLocal
        from db.models import DownloadJob as _DJ

        async with AsyncSessionLocal() as _sess:
            _result = await _sess.execute(sa_select(_DJ.user_id, _DJ.gallery_id).where(_DJ.id == db_job_id))
            _row = _result.one_or_none()
            if _row:
                import_user_id = _row.user_id
                existing_gallery_id = _row.gallery_id

    from worker.constants import _MEDIA_EXTS
    from worker.progressive import ProgressiveImporter

    # Use filename-based page numbering for plugins with parallel downloads
    page_from_filename = plugin.meta.concurrency > 1
    importer = ProgressiveImporter(db_job_id, import_user_id, page_num_from_filename=page_from_filename)
    importer.source_url = url
    if isinstance(existing_gallery_id, int):
        attached = await importer.attach_existing_gallery(existing_gallery_id)
        if not attached:
            logger.warning(
                "[download] persisted gallery_id=%s no longer exists; resolving gallery identity again",
                existing_gallery_id,
            )

    # ── 7. Pre-download metadata (native plugins) ──────────────────
    if hasattr(plugin, "resolve_metadata"):
        try:
            import_data = await plugin.resolve_metadata(url, credentials)
            if import_data:
                await importer.ensure_gallery_from_import_data(import_data)
                await _set_job_progress(
                    db_job_id,
                    {
                        **_base_progress,
                        "title": importer.title,
                        "gallery_id": importer.gallery_id,
                        "status_text": f"Downloading: {importer.title}",
                    },
                )
        except Exception as exc:
            logger.warning("[download] resolve_metadata failed (non-fatal): %s", exc)

    # ── 8. Progress callback ────────────────────────────────────────
    # Mutable container so the closure can observe updates made after acquire.
    timing_ctx: dict = {"semaphore_wait_ms": 0}
    diagnostic_ctx: dict = {}

    def _build_status_text(
        downloaded: int,
        total_pages: int,
        gdl_state: str,
        current_file: str | None,
        skipped: int,
        gdl_state_seconds: float | None,
    ) -> str:
        if gdl_state == "sleeping" and gdl_state_seconds:
            return f"Rate-limit cooldown: {gdl_state_seconds:.0f}s"
        if gdl_state == "rate_limited":
            cd = f" ({gdl_state_seconds:.0f}s)" if gdl_state_seconds else ""
            return f"Hit rate limit (429), waiting{cd}..."
        if gdl_state == "retrying":
            return "Server error — gallery-dl retrying..."
        if gdl_state == "paused":
            return "Paused"
        if gdl_state == "cancelled":
            return "Cancelling..."
        if current_file:
            tail = f" ({downloaded}/{total_pages})" if total_pages > 0 else f" ({downloaded})"
            return f"Downloading {current_file}{tail}"
        if skipped > 0 and downloaded == 0:
            # Re-download / subscription-up-to-date case: gallery-dl is hitting the archive.
            # Old images deleted by the user but archive entry still present also lands here.
            return f"Checking archive ({skipped} already saved)"
        if total_pages > 0:
            return f"Downloading... ({downloaded}/{total_pages})"
        return "Downloading..."

    async def on_progress(downloaded: int, total_pages: int) -> None:
        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        speed = round(downloaded / elapsed, 3) if elapsed > 0 else 0
        gdl_state = diagnostic_ctx.get("gdl_state", "downloading")
        current_file = diagnostic_ctx.get("current_file")
        current_file_page = diagnostic_ctx.get("current_file_page")
        skipped = diagnostic_ctx.get("skipped", 0)
        gdl_state_seconds = diagnostic_ctx.get("gdl_state_seconds")
        recent_log = diagnostic_ctx.get("recent_log") or []
        progress: dict = {
            **_base_progress,
            **({"total": total_pages} if total_pages > 0 else {}),
            "downloaded": downloaded,
            "skipped": skipped,
            "started_at": started_at.isoformat(),
            "last_update_at": datetime.now(UTC).isoformat(),
            "speed": speed,
            "status_text": _build_status_text(
                downloaded, total_pages, gdl_state, current_file, skipped, gdl_state_seconds
            ),
            "gdl_state": gdl_state,
        }
        if current_file:
            progress["current_file"] = current_file
        if current_file_page is not None:
            progress["current_file_page"] = current_file_page
        if gdl_state_seconds is not None:
            progress["gdl_state_seconds"] = gdl_state_seconds
        if recent_log:
            progress["recent_log"] = list(recent_log)
        if diagnostic_ctx.get("source_summary"):
            progress["source_summary"] = dict(diagnostic_ctx["source_summary"])
        # Progressive importer skip counters (different from gallery-dl's
        # archive skips — these fire post-download for excluded/duplicate/invalid).
        importer_skip = {
            "duplicate": importer._skip_duplicate,
            "excluded": importer._skip_excluded,
            "invalid": importer._skip_invalid,
        }
        if any(importer_skip.values()):
            progress["import_skipped"] = importer_skip
        if importer.title:
            progress["title"] = importer.title
        if importer.gallery_id:
            progress["gallery_id"] = importer.gallery_id
        timing = {
            "semaphore_wait_ms": timing_ctx.get("semaphore_wait_ms", 0),
            "total_pause_ms": timing_ctx.get("total_pause_ms", 0),
            "avg_page_ms": round(elapsed * 1000 / downloaded) if downloaded > 0 else 0,
            "last_page_ms": timing_ctx.get("last_page_ms", 0),
            "idle_ms": timing_ctx.get("idle_ms", 0),
            "idle_timeout_ms": _dl_params.inactivity_timeout * 1000,
            "started_at": started_at.isoformat(),
            "elapsed_ms": round(elapsed * 1000),
        }
        progress["timing"] = timing
        await _set_job_progress(db_job_id, progress)

    # ── 9. Cancel / Pause / PID callbacks ───────────────────────────
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

    async def on_file(file_path: Path, sha256: str | None = None):
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
                        await _set_job_progress(
                            db_job_id,
                            {
                                **_base_progress,
                                "title": importer.title,
                                "gallery_id": importer.gallery_id,
                                "status_text": f"Downloading: {importer.title}",
                            },
                        )
        await importer.import_file(file_path, sha256=sha256)

    # ── 11. Execute download ────────────────────────────────────────
    job_id_str = db_job_id or str(uuid.uuid4())

    # ── Pre-semaphore pause gate (for keep_paused recovery) ────────
    if db_job_id:
        pause_val = await redis.get(f"download:pause:{db_job_id}")
        if pause_val is not None:
            await _set_job_status(db_job_id, "paused")
            logger.info("[download] pre-semaphore pause gate: job %s is paused, skipping", db_job_id)
            return {"status": "paused"}

    try:
        wait_secs = await sem.acquire(job_id_str)
        timing_ctx["semaphore_wait_ms"] = round(wait_secs * 1000)
        if wait_secs > 0:
            logger.info("[download] acquired slot after %.1fs wait", wait_secs)
    except TimeoutError:
        err = "No download slot available — timed out waiting. Please try again later."
        logger.error("[download] %s", err)
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    try:
        # Build heartbeat callback + inject into options
        async def _sem_heartbeat() -> bool:
            """Return True if heartbeat succeeded, False if evicted."""
            alive = await sem.heartbeat(job_id_str)
            if not alive:
                logger.warning("[download] heartbeat lost (evicted) for %s", job_id_str)
            return alive

        # Inject semaphore heartbeat and config isolation into options
        opts = dict(options or {})
        opts["config_id"] = db_job_id
        opts["sem_heartbeat"] = _sem_heartbeat
        opts["inactivity_timeout"] = _dl_params.inactivity_timeout
        opts["timing_ctx"] = timing_ctx
        opts["diagnostic_ctx"] = diagnostic_ctx
        opts["job_context"] = (options or {}).get("job_context", "manual")
        # last_completed_at travels through SAQ as ISO string (JSON-safe);
        # source.py expects a datetime, so reify here.
        _lca_raw = (options or {}).get("last_completed_at")
        if isinstance(_lca_raw, str):
            try:
                opts["last_completed_at"] = datetime.fromisoformat(_lca_raw)
            except ValueError:
                logger.warning("[download] invalid last_completed_at isoformat: %r", _lca_raw)
                opts["last_completed_at"] = None
        else:
            opts["last_completed_at"] = _lca_raw

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
                options=opts,
            )
            # N8: cookie writeback (updated cookies → encrypted DB)
            if db_job_id and result.status in ("done", "partial"):
                try:
                    await _writeback_cookies(credentials, db_job_id)
                except Exception as exc:
                    logger.warning("[download] cookie writeback failed: %s", exc)
        except Exception as exc:
            err = f"Download failed: {exc}"
            logger.error("[download] %s", err, exc_info=True)
            await importer.abort()
            await _set_job_status(db_job_id, "failed", err)
            await _set_subscription_result(db_job_id, "failed", err)
            return {"status": "failed", "error": err}
        finally:
            if pid_key:
                try:
                    await redis.delete(pid_key)
                except Exception:
                    pass
    finally:
        await sem.release(job_id_str)
        # Fallback config cleanup (in case source.py missed it)
        config_path = Path(f"/app/config/gallery-dl-{db_job_id}.json") if db_job_id else None
        if config_path:
            config_path.unlink(missing_ok=True)

    # ── 12. Post-download: cancel guard ─────────────────────────────
    if result.status == "cancelled":
        await importer.cleanup()
        await _set_job_status(db_job_id, "cancelled")
        await _set_subscription_result(db_job_id, "cancelled")
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
            await _set_subscription_result(db_job_id, "failed", err)
            return {"status": "failed", "error": err}

    if await cancel_check():
        await importer.cleanup()
        await _set_job_status(db_job_id, "cancelled")
        await _set_subscription_result(db_job_id, "cancelled")
        logger.info("[download] cancelled (post-download guard): %s", url)
        return {"status": "cancelled"}

    try:
        # ── 13. Image validation ────────────────────────────────────────
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

        all_failed = sorted(set(getattr(result, "failed_pages", []) + corrupt_pages))

        # ── 14. Final progress update ───────────────────────────────────
        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        speed = round(result.downloaded / elapsed, 3) if elapsed > 0 else 0
        skipped_total = diagnostic_ctx.get("skipped", 0)
        if all_failed:
            final_status_text = f"Partial — {len(all_failed)} pages failed"
        elif result.downloaded == 0 and skipped_total > 0:
            # Subscription up-to-date / re-download where everything was already in archive
            final_status_text = f"Up to date — {skipped_total} already saved"
        elif skipped_total > 0:
            # Mixed run: subscription found new items + skipped existing ones
            final_status_text = f"Complete — {result.downloaded} new, {skipped_total} already saved"
        else:
            final_status_text = "Complete"
        final_progress = {
            **_base_progress,
            "total": result.total or result.downloaded,
            "downloaded": result.downloaded,
            "skipped": skipped_total,
            "started_at": started_at.isoformat(),
            "last_update_at": datetime.now(UTC).isoformat(),
            "speed": speed,
            "status_text": final_status_text,
            "gdl_state": "done",
        }
        if diagnostic_ctx.get("source_summary"):
            final_progress["source_summary"] = dict(diagnostic_ctx["source_summary"])
        importer_skip = {
            "duplicate": importer._skip_duplicate,
            "excluded": importer._skip_excluded,
            "invalid": importer._skip_invalid,
        }
        if any(importer_skip.values()):
            final_progress["import_skipped"] = importer_skip
        if importer.title:
            final_progress["title"] = importer.title
        if importer.gallery_id:
            final_progress["gallery_id"] = importer.gallery_id
        if all_failed:
            final_progress["failed_pages"] = all_failed
        await _set_job_progress(db_job_id, final_progress)

        # ── 15. Finalize ────────────────────────────────────────────────
        if target_dir.exists() and result.downloaded > 0:
            if importer.gallery_id:
                gallery_id = await importer.finalize(
                    target_dir, partial=bool(all_failed) or result.status in ("failed", "partial")
                )
                logger.info("[download] progressive import finalized: gallery_id=%s", gallery_id)
            else:
                # Safety fallback: no progressive import occurred (should be
                # rare). Complete it in this orchestration step so the DB job
                # cannot become "done" before ingest has committed.
                from worker.importer import import_job

                import_result = await import_job(
                    ctx,
                    path=str(target_dir),
                    db_job_id=db_job_id,
                    user_id=import_user_id,
                    source_url=url,
                )
                if import_result.get("status") != "done":
                    raise RuntimeError(import_result.get("error") or "Fallback import failed")
        elif result.downloaded == 0:
            logger.info("[download] no new files downloaded (all skipped by archive), skipping import: %s", url)

        is_partial = bool(all_failed) or result.status in ("failed", "partial")
        if is_partial:
            if all_failed:
                partial_msg = f"Partial — {len(all_failed)} pages failed"
                if result.error:
                    partial_msg = f"{partial_msg}; {result.error}"
            else:
                partial_msg = result.error or "Partial download"
            await _set_job_status(db_job_id, "partial", partial_msg)
            await _set_subscription_result(db_job_id, "partial", partial_msg)
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

        zero_run = result.downloaded == 0 and skipped_total == 0
        await _set_job_status(db_job_id, "done")
        await _set_subscription_result(db_job_id, "done", advance_success=not zero_run)
        if zero_run:
            logger.info(
                "[download] 0/0 run not advancing last_success_at: %s "
                "(date-after may have filtered all items, or extractor returned empty)",
                url,
            )
        logger.info("[download] done: %s (downloaded=%d)", url, result.downloaded)
        return {"status": "done", "downloaded": result.downloaded}

    except Exception as exc:
        # Guard: post-download steps (validation, finalize, status update) must never leave
        # a job stuck in 'running'. Downloaded bytes are not the same as a
        # committed gallery: post-processing failure is partial, never done.
        logger.error("[download] post-download steps failed: %s", exc, exc_info=True)
        fin_status = _postprocess_failure_status(result.downloaded)
        fin_err = f"Post-download error: {exc}"
        await _set_job_status(db_job_id, fin_status, fin_err)
        await _set_subscription_result(db_job_id, fin_status, fin_err)
        return {"status": fin_status, "downloaded": result.downloaded, "error": str(exc)}
