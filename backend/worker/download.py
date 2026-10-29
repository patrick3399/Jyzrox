"""Download job for the worker package."""

import asyncio
import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from core.config import settings
from core.events import EventType, emit_safe
from services.credential import get_credential
from services.download_admission import DownloadAdmission, admission_key_for
from services.download_mode import REPAIR, effective_mode
from services.download_stop import read_stop_intent
from worker.constants import _IMAGE_EXTS, _MEDIA_EXTS, DISK_LOW_KEY, logger
from worker.helpers import (
    _set_job_progress,
    _set_job_status,
    _validate_image_magic,
    check_disk_space,
    enqueue_finalize_stopped_job,
)

# Names gallery-dl and its post-processors leave while a file is still being written.
_STAGING_TEMP_SUFFIXES = (".part", ".ytdl", ".tmp")
# yt-dlp intermediates: `name.temp.mp4` and per-format fragments `name.f137.mp4`.
_STAGING_YTDLP_FRAGMENT_RE = re.compile(r"\.f\d+\.")


def _postprocess_failure_status(downloaded: int) -> str:
    """Never report a post-processing failure as a completed download."""
    return "partial" if downloaded > 0 else "failed"


def _run_fetched_count(result) -> int:
    """Pages whose bytes this run actually obtained.

    `result.downloaded` counts what the gallery holds once the run ends. Under
    incremental repair that includes pages skipped without a fetch, so a run
    stopped at the 509 wall before obtaining anything still reports a large
    `downloaded`. Demoting a failure to a partial success on that basis records
    a run that accomplished nothing as one that gained content. Only plugins
    that draw the distinction set `fetched`; the rest fall back unchanged.
    """
    fetched = getattr(result, "fetched", None)
    if type(fetched) is not int:
        return getattr(result, "downloaded", 0)
    return fetched


def _import_outcome(importer) -> tuple[tuple[dict[str, str], ...], int]:
    """Read the public progressive-import outcome without trusting loose mocks."""
    failures = getattr(importer, "import_failures", ())
    success_count = getattr(importer, "import_success_count", 0)
    if not isinstance(failures, tuple):
        failures = ()
    if type(success_count) is not int:
        success_count = 0
    return failures, success_count


async def _link_already_saved_gallery(db_job_id: str | None, url: str, source_id: str) -> dict | None:
    """Find the live gallery a fully archive-skipped run belongs to.

    A run that downloads nothing never reaches the importer, so the job would
    carry no gallery link. Resolve the URL identity read-only and attach the
    existing gallery to the job so the queue can point at it. Trashed
    galleries are not linked (BE-T17). Returns ``{"gallery_id", "title",
    "pages"}`` or ``None``; never raises.
    """
    if source_id != "gallery_dl":
        return None
    try:
        from sqlalchemy import select as sa_select

        from core.database import AsyncSessionLocal
        from db.models import DownloadJob, Gallery
        from plugins.builtin.gallery_dl._identity import resolve_url_identity

        identity = resolve_url_identity(url)
        if identity is None or identity.is_account:
            return None
        async with AsyncSessionLocal() as session:
            gallery = (
                await session.execute(
                    sa_select(Gallery.id, Gallery.title, Gallery.pages).where(
                        Gallery.source == identity.source,
                        Gallery.source_id == identity.source_id,
                        Gallery.deleted_at.is_(None),
                    )
                )
            ).one_or_none()
            if gallery is None:
                return None
            if db_job_id:
                job = await session.get(DownloadJob, uuid.UUID(db_job_id))
                if job is not None and job.gallery_id is None:
                    job.gallery_id = gallery.id
                    await session.commit()
            return {"gallery_id": gallery.id, "title": gallery.title, "pages": gallery.pages}
    except Exception as exc:
        logger.warning("[download] could not link already-saved gallery for %s: %s", url, exc)
        return None


async def _is_job_cancelled_in_db(db_job_id: str | None) -> bool:
    """Read the authoritative DB status for a DownloadJob.

    Used immediately before finalization (HR-005): the Redis cancel flag
    used by the earlier post-download guards can be evicted (Redis runs
    allkeys-lru in this deployment), so the last check before mutating the
    gallery must consult the DB row directly. DB `cancelled` always wins
    over a completed download.
    """
    if not db_job_id:
        return False
    from core.database import AsyncSessionLocal
    from db.models import DownloadJob

    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(DownloadJob, uuid.UUID(db_job_id))
            return bool(job and job.status == "cancelled")
    except Exception as exc:  # noqa: BLE001 - defensive, must never block finalize on lookup error
        logger.error("[download] failed to read job status for cancel check: %s", exc)
        return False


async def _writeback_cookies(
    credentials: dict | str | None, job_id: str, accounts: dict[str, str] | None = None
) -> None:
    """Read cookie update files written by gallery-dl's cookies-update PP and save to DB.

    ``accounts`` maps each source to the account its cookies were loaded from
    when the job started. The refreshed cookies go back to that account, not to
    whichever one is active by the time the job ends.
    """
    import http.cookiejar

    if not isinstance(credentials, dict):
        return

    from plugins.builtin.gallery_dl._sites import cookie_writeback_path, get_site_config
    from services.credential import DEFAULT_ACCOUNT, set_credential_for_account

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
                    account = (accounts or {}).get(src, DEFAULT_ACCOUNT)
                    if await set_credential_for_account(src, account, json.dumps(updated), "cookies"):
                        logger.info("[download] cookies updated for %s/%s (%d cookies)", src, account, len(updated))
                    else:
                        logger.info(
                            "[download] %s/%s was removed during the job; refreshed cookies dropped", src, account
                        )
        except Exception as exc:
            logger.warning("[download] failed to update cookies for %s: %s", src, exc)
        finally:
            cookie_path.unlink(missing_ok=True)


async def _load_credentials(plugin) -> tuple[dict | str | None, dict[str, str]]:
    """Return the plugin's credentials and, per source, the account each value came from.

    Value and account come from one read, so a switch of the active account
    between two lookups cannot pair one account's cookies with another's name.
    """
    if not plugin.meta.needs_all_credentials:
        return await get_credential(plugin.meta.source_id), {}

    from services.credential import get_active_credential, list_credentials

    values: dict[str, str] = {}
    accounts: dict[str, str] = {}
    for entry in await list_credentials():
        active = await get_active_credential(entry["source"])
        if active:
            values[entry["source"]] = active.value
            accounts[entry["source"]] = active.account
    return values, accounts


async def _set_subscription_result(
    db_job_id: str | None,
    status: str,
    error: str | None = None,
    *,
    advance_success: bool = True,
    boundary: datetime | None = None,
) -> None:
    """Update subscription status after the associated download reaches a terminal state.

    advance_success=False suppresses the last_success_at update even when status="done".
    Use this when gallery-dl returned 0 downloaded + 0 skipped: the run produced no
    evidence the source was actually checked (date-after may have filtered everything),
    so advancing the cutoff would self-poison the next incremental check.

    status="stopped" is a user ending the run early and keeping what it fetched.
    ``boundary`` (the run's start) becomes the new ``last_success_at`` unless the
    subscription already has a later one, so the next check fetches only what is
    newer and the history the user gave up is not pulled back. Without a boundary
    a stop leaves ``last_success_at`` alone.

    A repair job never moves ``last_success_at`` whatever its status: it re-fetches
    what a subscription already covers and owns no boundary.
    """
    if not db_job_id:
        return
    try:
        from sqlalchemy import func, update

        from core.database import AsyncSessionLocal
        from db.models import DownloadJob, Subscription

        async with AsyncSessionLocal() as session:
            job = await session.get(DownloadJob, uuid.UUID(db_job_id))
            if not job or not job.subscription_id:
                return
            subscription_id = job.subscription_id
            job_mode = effective_mode(
                job.mode if isinstance(job.mode, str) else None,
                job.options if isinstance(job.options, dict) else None,
            )
            values = {
                "last_status": status,
                "last_error": error[:500] if error else None,
            }
            if job_mode == REPAIR:
                pass
            elif status == "stopped":
                if boundary is not None:
                    values["last_success_at"] = func.greatest(
                        func.coalesce(Subscription.last_success_at, boundary), boundary
                    )
            elif status == "done" and advance_success:
                values["last_success_at"] = datetime.now(UTC)
            await session.execute(update(Subscription).where(Subscription.id == subscription_id).values(**values))
            await session.commit()

        # DL-007: track consecutive failures (alert + backoff for chronic ones)
        from services.subscription_health import record_check_result

        await record_check_result(subscription_id, status)
    except Exception as exc:
        logger.warning("[download] failed to update subscription result: %s", exc)


async def _enqueue_admission_redelivery(
    *,
    job_id: str,
    url: str,
    source: str,
    options: dict | None,
    total: int | None,
    delay_seconds: float,
) -> None:
    import core.queue

    await core.queue.enqueue(
        "download_job",
        _job_id=f"dispatch:{job_id}:{uuid.uuid4()}",
        _timeout=settings.download_job_timeout,
        _scheduled=int(time.time() + max(0.0, delay_seconds)),
        _ttl=-1,
        url=url,
        source=source,
        options=options,
        db_job_id=job_id,
        total=total,
    )


async def _wake_next_admission(key: str) -> None:
    """Best-effort immediate transport delivery for the oldest waiter."""
    from sqlalchemy import select

    from core.database import AsyncSessionLocal
    from db.models import DownloadJob

    try:
        async with asyncio.timeout(2):
            async with AsyncSessionLocal() as session:
                job = (
                    await session.execute(
                        select(DownloadJob)
                        .where(
                            DownloadJob.admission_key == key,
                            DownloadJob.status == "queued",
                            DownloadJob.admission_token.is_(None),
                        )
                        .order_by(DownloadJob.admission_ticket.asc(), DownloadJob.id.asc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if job is None:
                    return
                await _enqueue_admission_redelivery(
                    job_id=str(job.id),
                    url=job.url,
                    source=job.source or "",
                    options=job.options if isinstance(job.options, dict) else None,
                    total=(job.progress or {}).get("total"),
                    delay_seconds=0,
                )
    except Exception as exc:
        logger.warning("[download] failed to wake admission waiter for %s: %s", key, exc)


async def _admission_token_valid(job_id: str, token: uuid.UUID) -> bool:
    from core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        return await DownloadAdmission(session).token_is_valid(job_id, token)


async def _stop_intent(db_job_id: str | None) -> str | None:
    """Durable intent of the job (``"cancel"``, ``"stop"`` or ``None``); never raises."""
    if not db_job_id:
        return None
    return await read_stop_intent(db_job_id)


def _list_staged_media(target_dir: Path) -> list[Path]:
    """Finished media files in a staging dir, skipping what is still being written."""
    if not target_dir.exists():
        return []
    found: list[Path] = []
    for path in sorted(target_dir.rglob("*")):
        name = path.name
        if name.startswith(".") or name.endswith(_STAGING_TEMP_SUFFIXES):
            continue
        if ".temp." in name or _STAGING_YTDLP_FRAGMENT_RE.search(name):
            continue
        if path.suffix.lower() not in _MEDIA_EXTS:
            continue
        if path.is_file():
            found.append(path)
    return found


async def _import_staged_leftovers(importer, target_dir: Path, on_file) -> int:
    """Import the finished files in staging that never reached the importer.

    gallery-dl records a file in the archive before its ``after`` hook prints
    ``JYZROX_FILE``, so a run ended between the two leaves a file that is archived,
    on disk and unknown to the importer. Importing it here keeps the archive and
    the gallery in agreement. ``on_file`` creates the gallery when none exists
    yet. Returns how many files were handed over.
    """
    handed = 0
    for path in await asyncio.to_thread(_list_staged_media, target_dir):
        # Both checks are cheap and skip a file before it is hashed. A known name
        # means the gallery already holds it (`is True`: loose test doubles).
        if importer.has_processed(path) or importer.is_known_filename(path) is True:
            continue
        try:
            await on_file(path)
            handed += 1
        except Exception as exc:
            logger.warning("[download] could not import staged leftover %s: %s", path.name, exc)
    if handed:
        logger.info("[download] imported %d staged leftover file(s) from %s", handed, target_dir)
    return handed


def _count(value) -> int:
    """An int counter, or 0 for anything else (loose test doubles)."""
    return value if type(value) is int else 0


async def _finish_stopped(
    *,
    importer,
    target_dir: Path,
    url: str,
    plugin,
    on_file,
    db_job_id: str | None,
    mode: str,
    started_at: datetime,
    credentials,
    credential_accounts: dict[str, str] | None,
    result,
) -> dict:
    """Keep what a user-stopped run fetched and end the job ``done``.

    A failure here must not leave the job running with nobody to finish it, so it
    hands the job to ``finalize_stopped_job``: once this execution releases its
    admission token that task redoes the keep path from the database state.
    """
    try:
        return await _finish_stopped_inner(
            importer=importer,
            target_dir=target_dir,
            url=url,
            plugin=plugin,
            on_file=on_file,
            db_job_id=db_job_id,
            mode=mode,
            started_at=started_at,
            credentials=credentials,
            credential_accounts=credential_accounts,
            result=result,
        )
    except Exception as exc:
        logger.error("[download] keep path failed for stopped job %s: %s", db_job_id, exc, exc_info=True)
        if db_job_id:
            try:
                await enqueue_finalize_stopped_job(db_job_id)
            except Exception as enqueue_exc:
                logger.error("[download] could not hand stopped job %s to finalize: %s", db_job_id, enqueue_exc)
        return {"status": "stopping", "error": str(exc)}


async def _finish_stopped_inner(
    *,
    importer,
    target_dir: Path,
    url: str,
    plugin,
    on_file,
    db_job_id: str | None,
    mode: str,
    started_at: datetime,
    credentials,
    credential_accounts: dict[str, str] | None,
    result,
) -> dict:
    # 1. Files gallery-dl archived and left in staging without printing them (B1).
    await _import_staged_leftovers(importer, target_dir, on_file)

    # 2. A cancel that arrived after the stop wins (HR-005, A2): discard the run.
    if await _is_job_cancelled_in_db(db_job_id):
        await importer.cleanup()
        await _set_job_status(db_job_id, "cancelled")
        await _set_subscription_result(db_job_id, "cancelled")
        logger.info("[download] cancelled after stop (keep-path DB guard): %s", url)
        return {"status": "cancelled"}

    # 3. Keep. No gallery (stopped before anything imported) or a trashed one
    # (BE-T17) leaves nothing to keep, and the archive rows this run wrote would
    # make the next run skip files that were never imported (E5).
    gallery_id = None
    if importer.gallery_id and getattr(importer, "skipped_trashed", False) is not True:
        gallery_id = await importer.finalize_kept(target_dir, mode=mode)
    else:
        from worker.progressive import _rmtree_staging_dir

        if getattr(plugin.meta, "source_id", None) == "gallery_dl" and not importer.source:
            # The archive table is named after the source; a run that never created
            # a gallery has none yet, so without it the discard would find no table.
            try:
                from plugins.builtin.gallery_dl._identity import resolve_url_identity

                identity = resolve_url_identity(url)
                if identity is not None:
                    importer.source = identity.source
            except Exception as exc:
                logger.warning("[download] could not resolve archive source for %s: %s", url, exc)
        await importer.discard_unlinked_archive_entries()
        _rmtree_staging_dir(target_dir)

    # 4. Cookie writeback, as for a finished run.
    if db_job_id:
        try:
            await _writeback_cookies(credentials, db_job_id, credential_accounts)
        except Exception as exc:
            logger.warning("[download] cookie writeback failed: %s", exc)

    # 5. A stop always ends `done` (never failed/partial, which auto-retry would
    # resume — A10); progress.outcome tells the UI what happened.
    import_failures, kept = _import_outcome(importer)
    fetched = _count(getattr(result, "downloaded", None)) or kept
    skipped = max(_count(getattr(result, "total", None)) - _count(getattr(result, "downloaded", None)), 0)
    progress: dict = {
        "total": fetched,
        "downloaded": fetched,
        "skipped": skipped,
        "started_at": started_at.isoformat(),
        "last_update_at": datetime.now(UTC).isoformat(),
        "status_text": f"Stopped — kept {kept}",
        "gdl_state": "done",
        "outcome": "stopped",
    }
    importer_skip = {
        "duplicate": _count(importer.skipped_duplicate_count),
        "excluded": _count(importer.skipped_excluded_count),
        "invalid": _count(importer.skipped_invalid_count),
    }
    if any(importer_skip.values()):
        progress["import_skipped"] = importer_skip
    if isinstance(importer.title, str) and importer.title:
        progress["title"] = importer.title
    if gallery_id:
        progress["gallery_id"] = gallery_id
    if import_failures:
        progress["import_failures"] = {
            "count": len(import_failures),
            "success": kept,
            "details": list(import_failures[:10]),
        }
    await _set_job_progress(db_job_id, progress)
    await _set_job_status(db_job_id, "done")

    # 6. The subscription boundary moves to the run start, never backwards.
    await _set_subscription_result(db_job_id, "stopped", boundary=started_at)

    # 7. Library refresh.
    if gallery_id:
        await emit_safe(EventType.GALLERY_UPDATED, resource_type="gallery", resource_id=gallery_id)

    logger.info("[download] stopped: %s (kept=%d, gallery_id=%s)", url, kept, gallery_id)
    return {"status": "done", "outcome": "stopped", "downloaded": fetched}


async def download_job(
    ctx: dict,
    url: str,
    source: str = "",
    options: dict | None = None,
    db_job_id: str | None = None,
    total: int | None = None,
) -> dict:
    """Claim durable source capacity before starting any expensive work."""
    logger.info("[download] url=%s", url)
    from plugins.registry import plugin_registry

    plugin = await plugin_registry.get_handler(url)
    if not plugin:
        plugin = plugin_registry.get_fallback()
    if not plugin:
        err = "No plugin can handle this URL"
        logger.error("[download] %s", err)
        changed = await _set_job_status(db_job_id, "failed", err, required_current_status="queued")
        if changed:
            await _set_subscription_result(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    from core.site_config import site_config_service

    source_id = plugin.meta.source_id
    admission_key = plugin.meta.semaphore_key or source_id
    site_source_id = source_id
    if source_id == "gallery_dl":
        from plugins.builtin.gallery_dl._sites import get_site_by_domain

        domain = (urlparse(url).hostname or "unknown").removeprefix("www.")
        site_source_id = get_site_by_domain(domain).source_id
        dl_params = await site_config_service.get_effective_download_params(site_source_id)
        if admission_key == "gallery_dl":
            admission_key = admission_key_for("gallery_dl", url)
    else:
        dl_params = await site_config_service.get_effective_download_params(source_id)

    if not db_job_id:
        return await _run_download_job(
            ctx, url, source, options, db_job_id, total, plugin=plugin, dl_params=dl_params, admission_token=None
        )

    from core.database import AsyncSessionLocal
    from services.egress_persona import claim_download_slot

    async with AsyncSessionLocal() as session:
        decision = await claim_download_slot(
            session,
            job_id=db_job_id,
            base_key=admission_key,
            site_source_id=site_source_id,
            capacity=dl_params.concurrency,
            admission=DownloadAdmission(session),
        )
    claim = decision.claim
    admission_key = decision.key
    if not claim.acquired:
        # A token-less result with no queue position means the durable row is
        # no longer queued (cancelled, paused, terminal, or a duplicate active
        # delivery). Never schedule or mutate it from this stale attempt.
        if claim.queue_position is None:
            return {"status": "ignored"}
        base_progress = {} if total is None else {"total": total}
        await _set_job_progress(
            db_job_id,
            {
                **base_progress,
                "status_text": "Waiting for download slot...",
                "wait_reason": "persona_cooldown" if decision.personas_cooling else "source_slot",
                "semaphore_key": admission_key,
                "queue_position": claim.queue_position,
            },
        )
        await _enqueue_admission_redelivery(
            job_id=db_job_id,
            url=url,
            source=source,
            options=options,
            total=total,
            delay_seconds=60 if decision.personas_cooling else 5,
        )
        return {"status": "queued", "queue_position": claim.queue_position}

    try:
        running_confirmed = await _set_job_status(db_job_id, "running", required_current_status="running")
        if not running_confirmed:
            # Cancel/pause may win immediately after claim commits. Do not let
            # this execution touch credentials, disk, metadata, importer, or
            # the source plugin after durable state rejects the running guard.
            return {"status": "ignored"}
        return await _run_download_job(
            ctx,
            url,
            source,
            options,
            db_job_id,
            total,
            plugin=plugin,
            dl_params=dl_params,
            admission_token=claim.token,
            persona_id=claim.persona_id if decision.persona_mode else None,
            site_source_id=site_source_id,
        )
    finally:
        released = False
        try:
            async with AsyncSessionLocal() as session:
                released = await DownloadAdmission(session).release(db_job_id, claim.token)
        except Exception as exc:
            logger.error("[download] failed to release admission token for %s: %s", db_job_id, exc)
        if released:
            await _wake_next_admission(admission_key)


async def _run_download_job(
    ctx: dict,
    url: str,
    source: str = "",
    options: dict | None = None,
    db_job_id: str | None = None,
    total: int | None = None,
    *,
    plugin,
    dl_params,
    admission_token: uuid.UUID | None,
    persona_id: int | None = None,
    site_source_id: str | None = None,
) -> dict:
    """Download a gallery via the plugin registry — unified progressive import."""
    logger.info("[download] url=%s", url)

    started_at = datetime.now(UTC)

    from plugins.registry import plugin_registry

    source_id = plugin.meta.source_id

    # ── 2. Load credentials (unified) ───────────────────────────────
    credentials, credential_accounts = await _load_credentials(plugin)

    # ADR 0022: a persona job swaps the site's active account for its bound one
    # (or none); credential_accounts then feeds the cookie writeback below.
    persona_identity = None
    if persona_id is not None and site_source_id:
        from services.egress_persona import PersonaUnavailable, prepare_persona_run

        try:
            persona_identity, credentials, credential_accounts = await prepare_persona_run(
                persona_id, site_source_id, credentials, credential_accounts
            )
        except PersonaUnavailable as exc:
            err = str(exc)
            logger.error("[download] %s", err)
            await _set_job_status(db_job_id, "failed", err)
            return {"status": "failed", "error": err}

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

    _base_progress: dict = {} if total is None else {"total": total}

    # ── 6. Progressive Importer (ALL sources) ───────────────────────
    import_user_id = None
    existing_gallery_id = None
    row_mode = None
    row_options = None
    stop_already_requested = False
    if db_job_id:
        from sqlalchemy.sql import select as sa_select

        from core.database import AsyncSessionLocal
        from db.models import DownloadJob as _DJ

        try:
            async with asyncio.timeout(2):
                async with AsyncSessionLocal() as _sess:
                    _result = await _sess.execute(
                        sa_select(_DJ.user_id, _DJ.gallery_id, _DJ.mode, _DJ.options, _DJ.stop_requested_at).where(
                            _DJ.id == db_job_id
                        )
                    )
                    _row = _result.one_or_none()
                    if _row:
                        import_user_id = _row.user_id
                        existing_gallery_id = _row.gallery_id
                        row_mode = _row.mode
                        row_options = _row.options
                        # A stop requested while the job waited for its slot: it never starts.
                        stop_already_requested = isinstance(_row.stop_requested_at, datetime)
        except Exception as exc:
            # Admission already verified the durable row. Keep this lookup
            # defensive for isolated unit execution and transient read errors.
            # (A stop missed here is still caught by the Redis flag the plugin polls.)
            logger.warning("[download] could not load persisted gallery attachment: %s", exc)

    # The mode was decided when the job was enqueued; rows from before the column
    # existed are mapped from their options (services/download_mode.py).
    mode_options = row_options if isinstance(row_options, dict) else options
    mode = effective_mode(row_mode if isinstance(row_mode, str) else None, mode_options)

    from worker.progressive import ProgressiveImporter

    # Use filename-based page numbering for plugins with parallel downloads
    page_from_filename = plugin.meta.concurrency > 1
    importer = ProgressiveImporter(
        db_job_id,
        import_user_id,
        page_num_from_filename=page_from_filename,
        # Only a repair may bring purged images back.
        include_excluded=bool((mode_options or {}).get("include_excluded")) and mode == REPAIR,
    )
    importer.source_url = url
    if mode == REPAIR and source_id == "gallery_dl" and db_job_id:
        # The repair reads and writes a per-job shadow of the real archive table;
        # the importer merges it back when the run is kept (source.py creates it).
        try:
            from plugins.builtin.gallery_dl._archive import repair_archive_tables

            importer.repair_archive = repair_archive_tables(url, db_job_id)
        except Exception as exc:
            logger.warning("[download] could not resolve repair archive tables for %s: %s", url, exc)
    if isinstance(existing_gallery_id, int):
        attached = await importer.attach_existing_gallery(existing_gallery_id)
        if not attached:
            logger.warning(
                "[download] persisted gallery_id=%s no longer exists; resolving gallery identity again",
                existing_gallery_id,
            )

    # ── 7. Pre-download metadata (native plugins) ──────────────────
    if hasattr(plugin, "resolve_metadata") and not stop_already_requested:
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
            "duplicate": importer.skipped_duplicate_count,
            "excluded": importer.skipped_excluded_count,
            "invalid": importer.skipped_invalid_count,
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
            "idle_timeout_ms": dl_params.inactivity_timeout * 1000,
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
                    raw: dict | None = None
                    if meta_path.exists():
                        try:
                            raw = json.loads(meta_path.read_text(encoding="utf-8"))
                        except Exception as exc:
                            logger.warning("[download] failed to parse metadata: %s", exc)
                    identity = None
                    if plugin.meta.source_id == "gallery_dl":
                        from plugins.builtin.gallery_dl._identity import resolve_url_identity

                        identity = resolve_url_identity(url)
                    try:
                        if identity is not None:
                            await importer.ensure_gallery_from_identity(identity, raw, target_dir)
                        elif raw is not None:
                            await importer.ensure_gallery(raw, target_dir)
                    except Exception as exc:
                        logger.warning("[download] failed to create gallery from metadata: %s", exc)
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

    async def _stop_and_keep(run_result) -> dict:
        return await _finish_stopped(
            importer=importer,
            target_dir=target_dir,
            url=url,
            plugin=plugin,
            on_file=on_file,
            db_job_id=db_job_id,
            mode=mode,
            started_at=started_at,
            credentials=credentials,
            credential_accounts=credential_accounts,
            result=run_result,
        )

    # ── 11. Execute download ────────────────────────────────────────
    # A stop that arrived before the job started: nothing to download, only the
    # keep path (leftover staging from an earlier attempt, archive rows, boundary).
    # Ahead of the pause gate, or a paused job would sit there with its stop unserved.
    if stop_already_requested:
        logger.info("[download] stop requested before start: %s", db_job_id)
        return await _stop_and_keep(None)

    # ── Pre-download pause gate (for keep_paused recovery) ─────────
    if db_job_id:
        pause_val = await redis.get(f"download:pause:{db_job_id}")
        if pause_val is not None:
            await _set_job_status(db_job_id, "paused")
            logger.info("[download] pre-download pause gate: job %s is paused, skipping", db_job_id)
            return {"status": "paused"}

    try:

        async def _sem_heartbeat() -> bool:
            """Return whether this execution still owns its database fence."""
            if not db_job_id or admission_token is None:
                return True
            alive = await _admission_token_valid(db_job_id, admission_token)
            if not alive:
                logger.warning("[download] admission token lost for %s", db_job_id)
            return alive

        # Inject semaphore heartbeat and config isolation into options
        opts = dict(options or {})
        opts["config_id"] = db_job_id
        opts["sem_heartbeat"] = _sem_heartbeat
        opts["inactivity_timeout"] = dl_params.inactivity_timeout
        opts["timing_ctx"] = timing_ctx
        opts["diagnostic_ctx"] = diagnostic_ctx
        if persona_identity is not None:
            opts["persona"] = persona_identity.network_options()
        opts["job_context"] = (options or {}).get("job_context", "manual")
        opts["mode"] = mode
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
        # Repairing a partial gallery must not re-fetch what it already holds.
        # Only meaningful when this run attached to a pre-existing gallery;
        # plugins that do not address pages by number ignore it.
        if importer.existing_page_nums:
            opts["skip_pages"] = importer.existing_page_nums

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
                await _writeback_cookies(credentials, db_job_id, credential_accounts)
            except Exception as exc:
                logger.warning("[download] cookie writeback failed: %s", exc)
    except Exception as exc:
        err = f"Download failed: {exc}"
        logger.error("[download] %s", err, exc_info=True)
        # The user stopped the job and the plugin then failed (or was torn down):
        # the stop still wins, and what was fetched is kept.
        if await _stop_intent(db_job_id) == "stop":
            return await _stop_and_keep(None)
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
        # Fallback config cleanup (in case source.py missed it)
        config_path = Path(f"/app/config/gallery-dl-{db_job_id}.json") if db_job_id else None
        if config_path:
            config_path.unlink(missing_ok=True)

    # Outside the try above: a cooldown failure must not turn a partial result into failed.
    if persona_identity is not None and result.status in ("failed", "partial"):
        from services.egress_persona import mark_persona_cooldown, throttle_signal

        signal = throttle_signal(diagnostic_ctx)
        if signal:
            await mark_persona_cooldown(persona_identity.persona_id, site_source_id, signal)

    # ── 12. Post-download: stop / cancel guards ─────────────────────
    # A stop keeps the run whatever the plugin reported: the process was killed
    # (cancelled), or died/timed out at the same moment (failed/partial, A9). A
    # run that finished (`done`) before the stop landed is simply finished (A1).
    if result.status != "done" and await _stop_intent(db_job_id) == "stop":
        return await _stop_and_keep(result)

    if result.status == "cancelled":
        # The Redis flag that ended the process is only a signal: re-read the
        # durable intent before throwing the run away.
        if await _stop_intent(db_job_id) == "stop":
            return await _stop_and_keep(result)
        await importer.cleanup()
        await _set_job_status(db_job_id, "cancelled")
        await _set_subscription_result(db_job_id, "cancelled")
        return {"status": "cancelled"}

    if result.status == "failed":
        # Gate on what this run fetched, not on what the gallery holds: a repair
        # that hit the 509 wall before obtaining a byte still reports every page
        # it skipped as `downloaded`, and demoting that to "partial" would hide a
        # run worth retrying behind a status that reads like progress.
        if _run_fetched_count(result) > 0 and importer.gallery_id:
            logger.warning(
                "[download] treating failed download as partial (fetched=%d of downloaded=%d): %s",
                _run_fetched_count(result),
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
        # The stop flag shares the key with cancel. A stop landing after the plugin
        # finished changes nothing (A1); otherwise it keeps the run.
        intent = await _stop_intent(db_job_id)
        if intent == "stop" and result.status != "done":
            return await _stop_and_keep(result)
        if intent != "stop":
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
        already_saved = result.downloaded == 0 and skipped_total > 0 and not all_failed
        saved_gallery = None
        if already_saved and not importer.gallery_id:
            saved_gallery = await _link_already_saved_gallery(db_job_id, url, plugin.meta.source_id)
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
            "duplicate": importer.skipped_duplicate_count,
            "excluded": importer.skipped_excluded_count,
            "invalid": importer.skipped_invalid_count,
        }
        if any(importer_skip.values()):
            final_progress["import_skipped"] = importer_skip
        if importer.title:
            final_progress["title"] = importer.title
        if importer.gallery_id:
            final_progress["gallery_id"] = importer.gallery_id
        if already_saved:
            # Nothing new was fetched: tell the UI this run only confirmed what
            # is already stored, instead of leaving it to guess from counters.
            final_progress["outcome"] = "already_saved"
            if saved_gallery:
                final_progress["gallery_id"] = saved_gallery["gallery_id"]
                final_progress["title"] = saved_gallery["title"]
                final_progress["existing_pages"] = saved_gallery["pages"]
        if all_failed:
            final_progress["failed_pages"] = all_failed
        await _set_job_progress(db_job_id, final_progress)

        # ── 15. Finalize ────────────────────────────────────────────────
        # Last-chance cancel check against the authoritative DB status,
        # immediately before mutating the gallery. This closes the race
        # where the Redis cancel flag was evicted (allkeys-lru) or set
        # after the earlier post-download guards already passed (HR-005).
        if await _is_job_cancelled_in_db(db_job_id):
            if await _stop_intent(db_job_id) == "stop":
                return await _stop_and_keep(result)
            await importer.cleanup()
            await _set_job_status(db_job_id, "cancelled")
            await _set_subscription_result(db_job_id, "cancelled")
            logger.info("[download] cancelled (pre-finalize DB guard): %s", url)
            return {"status": "cancelled"}

        if target_dir.exists() and result.downloaded > 0:
            if importer.gallery_id:
                gallery_id = await importer.finalize(
                    target_dir, partial=bool(all_failed) or result.status in ("failed", "partial")
                )
                logger.info("[download] progressive import finalized: gallery_id=%s", gallery_id)
                # HR-002: record per-file import failures in the structured
                # progress payload so a "done" job that silently dropped
                # files is visible, not just logged.
                import_failures, import_success_count = _import_outcome(importer)
                if import_failures:
                    final_progress["import_failures"] = {
                        "count": len(import_failures),
                        "success": import_success_count,
                        "details": list(import_failures[:10]),
                    }
                    await _set_job_progress(db_job_id, final_progress)
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

        # HR-002: if every file the importer attempted in this run failed and
        # none succeeded, the run is a genuine failure — not "done" and not
        # merely "partial" — regardless of what gallery-dl itself reported.
        import_failures, import_success_count = _import_outcome(importer)
        if importer.download_status == "failed":
            import_failure_count = len(import_failures)
            err = "All downloaded files failed to import"
            if import_failures:
                first = import_failures[0]
                err = f"{err}: {first['filename']} ({first['error_type']}: {first['error']})"
            await _set_job_status(db_job_id, "failed", err)
            await _set_subscription_result(db_job_id, "failed", err)
            logger.error(
                "[download] all imported files failed: %s failures=%d",
                url,
                import_failure_count,
            )
            return {"status": "failed", "error": err, "import_failures": import_failure_count}

        is_partial = bool(all_failed) or result.status in ("failed", "partial") or bool(import_failures)
        if is_partial:
            if import_failures and not all_failed and result.status not in ("failed", "partial"):
                partial_msg = (
                    f"Partial — {len(import_failures)} file(s) failed to import ({import_success_count} succeeded)"
                )
            elif all_failed:
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
        fin_status = _postprocess_failure_status(_run_fetched_count(result))
        fin_err = f"Post-download error: {exc}"
        await _set_job_status(db_job_id, fin_status, fin_err)
        await _set_subscription_result(db_job_id, fin_status, fin_err)
        return {"status": fin_status, "downloaded": result.downloaded, "error": str(exc)}
