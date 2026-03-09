"""
ARQ Worker entry point.

Run with:  arq worker.WorkerSettings

Workers:
  A  download_job   — gallery-dl download
  B  import_job     — gallery ingest into DB + tag upsert
  C  tag_job        — AI tagging stub (WD14 disabled)
  D  thumbnail_job  — multi-size WebP thumbnail generation
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import sqlalchemy.exc
from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

from core.config import get_all_library_paths, settings
from core.database import AsyncSessionLocal
from core.redis_client import DownloadSemaphore, close_redis, init_redis
from core.watcher import LibraryWatcher
from db.models import Blob, DownloadJob, Gallery, GalleryTag, Image, Tag
from services.cas import cas_path, create_library_symlink, decrement_ref_count, library_dir, resolve_blob_path, store_blob, thumb_dir
from services.credential import get_credential
from services.eh_client import _GALLERY_URL_RE as EH_GALLERY_URL_RE
from services.eh_downloader import download_eh_gallery

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"}


# ── Lifecycle ────────────────────────────────────────────────────────


_watcher = LibraryWatcher()


async def startup(ctx: dict) -> None:
    logger.info("ARQ Worker started — Jyzrox")
    await init_redis()
    r = ctx["redis"]
    for key in ("download:sem:ehentai", "download:sem:pixiv", "download:sem:other"):
        await r.delete(key)
    # Clean up stale scan progress from previous runs
    await r.delete("rescan:progress", "rescan:cancel")

    # Start file system watcher.
    # Honour the runtime override stored by toggle_monitor; fall back to the
    # static config flag when no override has been set yet.
    watcher_enabled_raw = await r.get("watcher:enabled")
    if watcher_enabled_raw is None:
        # No override stored — initialise from config and persist it.
        watcher_should_start = settings.library_monitor_enabled
        await r.set("watcher:enabled", "1" if watcher_should_start else "0")
    else:
        watcher_should_start = watcher_enabled_raw not in (b"0", "0")

    if watcher_should_start:
        paths = await get_all_library_paths()
        loop = asyncio.get_event_loop()
        arq_pool = ctx["redis"]

        def enqueue_sync(job_name: str, *args):
            asyncio.run_coroutine_threadsafe(
                arq_pool.enqueue_job(job_name, *args), loop
            )

        _watcher.start(paths, enqueue_sync)
        await r.set(
            "watcher:status",
            json.dumps({"running": True, "paths": paths}),
        )


async def shutdown(ctx: dict) -> None:
    logger.info("ARQ Worker shutting down")
    _watcher.stop()
    r = ctx["redis"]
    await r.delete("watcher:status")
    await close_redis()


# ── WORKER A: Download ───────────────────────────────────────────────


_FILE_PATH_RE = re.compile(r"/data/")
_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|gif|webp|avif|heic)$", re.IGNORECASE)
_PROGRESS_EVERY_N = 5       # update DB every N files downloaded
_PROGRESS_EVERY_S = 10.0    # or every N seconds, whichever comes first


async def download_job(
    ctx: dict,
    url: str,
    source: str = "",
    options: dict | None = None,
    db_job_id: str | None = None,
    total: int | None = None,
) -> dict:
    """Download a gallery via gallery-dl with async subprocess and progress tracking."""
    logger.info("[download] url=%s", url)

    await _set_job_status(db_job_id, "running")
    started_at = datetime.now(UTC)

    # Removed domain whitelist to allow any gallery-dl supported site

    # Pre-flight: check credentials for the source
    cred_error = await _check_credentials(url)
    if cred_error:
        logger.error("[download] %s", cred_error)
        await _set_job_status(db_job_id, "failed", cred_error)
        return {"status": "failed", "error": cred_error}

    # Native EH download path (bypasses gallery-dl)
    if _detect_source(url) == "ehentai":
        return await _eh_native_download(ctx, url, db_job_id, total)

    sem = DownloadSemaphore(_detect_source(url))
    _base_progress: dict = {} if total is None else {"total": total}
    await _set_job_progress(db_job_id, {**_base_progress, "status_text": "Waiting for download slot..."})
    async with sem.acquire():
        await _build_gallery_dl_config(url)
        
        # Isolate this job's downloads into a specific UUID directory
        target_dir = Path(settings.data_gallery_path) / (db_job_id or "local_test")
        
        cmd = [
            "gallery-dl",
            "--config-ignore",
            "--config",
            settings.gallery_dl_config,
            "--write-metadata",
            "--write-tags",
            "--directory",
            str(target_dir),
            url,
        ]

        redis = ctx["redis"]
        pid_key = f"download:pid:{db_job_id}" if db_job_id else None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            err = f"Failed to start gallery-dl: {exc}"
            logger.error("[download] %s", err)
            await _set_job_status(db_job_id, "failed", err)
            return {"status": "failed", "error": err}

        # Store PID in Redis for pause/resume and cancel
        if pid_key:
            try:
                await redis.set(pid_key, proc.pid, ex=3600)
            except Exception as exc:
                logger.warning("[download] failed to store PID in Redis: %s", exc)

        # Stream stdout line by line to track progress
        downloaded = 0
        last_progress_update = asyncio.get_event_loop().time()

        async def _read_stdout() -> None:
            nonlocal downloaded, last_progress_update
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if _FILE_PATH_RE.search(line) or _IMAGE_EXT_RE.search(line):
                    downloaded += 1
                    now = asyncio.get_event_loop().time()
                    if downloaded % _PROGRESS_EVERY_N == 0 or (now - last_progress_update) >= _PROGRESS_EVERY_S:
                        last_progress_update = now
                        elapsed = (datetime.now(UTC) - started_at).total_seconds()
                        speed = round(downloaded / elapsed, 3) if elapsed > 0 else 0
                        await _set_job_progress(db_job_id, {
                            **_base_progress,
                            "downloaded": downloaded,
                            "started_at": started_at.isoformat(),
                            "last_update_at": datetime.now(UTC).isoformat(),
                            "speed": speed,
                            "status_text": "Downloading...",
                        })

        try:
            # Read stdout concurrently while waiting for the process; apply a
            # generous timeout matching the ARQ job_timeout setting.
            await asyncio.wait_for(
                asyncio.gather(_read_stdout(), proc.wait()),
                timeout=3600,
            )
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            logger.error("[download] timeout: %s", url)
            # PID key cleanup handled in finally below
            await _set_job_status(db_job_id, "failed", "download timeout after 3600s")
            return {"status": "failed", "error": "timeout"}
        finally:
            # Always clean up the PID key once the process is done or killed
            if pid_key:
                try:
                    await redis.delete(pid_key)
                except Exception:
                    pass

        # Collect stderr for error reporting
        stderr_bytes = await proc.stderr.read() if proc.stderr else b""
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            err = stderr_text[:500]
            logger.error("[download] gallery-dl error:\n%s", stderr_text)
            await _set_job_status(db_job_id, "failed", err)
            return {"status": "failed", "error": err}

        logger.info("[download] done: %s (files=%d)", url, downloaded)

        # Final progress update with total count
        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        speed = round(downloaded / elapsed, 3) if elapsed > 0 else 0
        await _set_job_progress(db_job_id, {
            **_base_progress,
            "downloaded": downloaded,
            "started_at": started_at.isoformat(),
            "last_update_at": datetime.now(UTC).isoformat(),
            "speed": speed,
            "status_text": "Complete",
        })

        # Trigger import for the target directory
        if target_dir.exists():
            await ctx["redis"].enqueue_job("import_job", str(target_dir), db_job_id)

        await _set_job_status(db_job_id, "done")
        return {"status": "done", "downloaded": downloaded}


async def _check_credentials(url: str) -> str | None:
    """Return an error message if required credentials are missing, else None."""
    is_pixiv = "pixiv.net" in url
    is_eh = "e-hentai.org" in url or "exhentai.org" in url

    if is_pixiv:
        cred = await get_credential("pixiv")
        if not cred:
            return "Pixiv credentials not configured. Go to Settings to add your refresh token."
    elif is_eh:
        cred = await get_credential("ehentai")
        if not cred:
            return "E-Hentai credentials not configured. Go to Settings to add cookies."
    return None


async def _build_gallery_dl_config(url: str) -> None:
    """Write source-specific credentials into the gallery-dl config file."""
    config: dict = {
        "extractor": {
            "base-directory": settings.data_gallery_path,
        },
    }

    is_eh = "e-hentai.org" in url or "exhentai.org" in url
    is_pixiv = "pixiv.net" in url

    if is_eh:
        cred_json = await get_credential("ehentai")
        if cred_json:
            cookies = json.loads(cred_json)
            # Apply to both e-hentai and exhentai extractors
            config["extractor"]["exhentai"] = {"cookies": cookies}
            config["extractor"]["e-hentai"] = {"cookies": cookies}
    elif is_pixiv:
        token = await get_credential("pixiv")
        if token:
            config["extractor"]["pixiv"] = {"refresh-token": token}

    config_path = Path(settings.gallery_dl_config)
    tmp_path = config_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(config, indent=2))
    os.rename(tmp_path, config_path)


def _detect_source(url: str) -> str:
    """Detect download source from URL for semaphore selection."""
    if "e-hentai.org" in url or "exhentai.org" in url:
        return "ehentai"
    try:
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname
    except Exception:
        pass
    return "other"


async def _eh_native_download(ctx: dict, url: str, db_job_id: str | None, total: int | None) -> dict:
    """Native EH download using EhClient instead of gallery-dl."""
    logger.info("[download] native EH path: %s", url)
    started_at = datetime.now(UTC)

    # Parse gid and token from URL
    m = EH_GALLERY_URL_RE.search(url)
    if not m:
        err = f"Cannot parse EH gallery URL: {url}"
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    gid = int(m.group(1))
    token = m.group(2)
    use_ex = "exhentai.org" in url

    # Load cookies
    cred_json = await get_credential("ehentai")
    if not cred_json:
        err = "E-Hentai credentials not configured"
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}
    cookies = json.loads(cred_json)

    # Output directory
    output_dir = Path(settings.data_gallery_path) / "ehentai" / str(gid)

    # Cancel key in Redis
    cancel_key = f"download:cancel:{db_job_id}" if db_job_id else None

    # Progress callback
    async def on_progress(downloaded: int, total_pages: int) -> None:
        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        speed = round(downloaded / elapsed, 3) if elapsed > 0 else 0
        await _set_job_progress(db_job_id, {
            "total": total_pages,
            "downloaded": downloaded,
            "started_at": started_at.isoformat(),
            "last_update_at": datetime.now(UTC).isoformat(),
            "speed": speed,
            "status_text": f"Downloading... ({downloaded}/{total_pages})",
        })

    sem = DownloadSemaphore("ehentai")
    await _set_job_progress(db_job_id, {"status_text": "Waiting for download slot...", **({"total": total} if total else {})})

    async with sem.acquire():
        try:
            result = await download_eh_gallery(
                gid=gid,
                token=token,
                cookies=cookies,
                use_ex=use_ex,
                output_dir=output_dir,
                concurrency=settings.eh_download_concurrency,
                on_progress=on_progress,
                cancel_key=cancel_key,
            )
        except PermissionError as exc:
            err = str(exc)
            logger.error("[download] EH permission error: %s", err)
            await _set_job_status(db_job_id, "failed", err)
            return {"status": "failed", "error": err}
        except Exception as exc:
            err = f"Native EH download failed: {exc}"
            logger.error("[download] %s", err, exc_info=True)
            await _set_job_status(db_job_id, "failed", err)
            return {"status": "failed", "error": err}

    if result["status"] == "cancelled":
        await _set_job_status(db_job_id, "cancelled")
        return {"status": "cancelled"}

    if result["status"] == "failed":
        err = result.get("error", "Download failed")
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    # Final progress
    elapsed = (datetime.now(UTC) - started_at).total_seconds()
    downloaded_count = result.get("downloaded", 0)
    speed = round(downloaded_count / elapsed, 3) if elapsed > 0 else 0
    await _set_job_progress(db_job_id, {
        "total": result.get("total", downloaded_count),
        "downloaded": downloaded_count,
        "started_at": started_at.isoformat(),
        "last_update_at": datetime.now(UTC).isoformat(),
        "speed": speed,
        "status_text": "Complete",
    })

    # Trigger import
    if output_dir.exists():
        await ctx["redis"].enqueue_job("import_job", str(output_dir), db_job_id)

    await _set_job_status(db_job_id, "done")

    if result.get("failed_pages"):
        logger.warning("[download] %d pages failed: %s", len(result["failed_pages"]), result["failed_pages"])

    return {"status": "done", "downloaded": downloaded_count}


def _resolve_gallery_dir(url: str) -> Path | None:
    """Guess the gallery directory path from the URL."""
    m = re.search(r"e[x\-]hentai\.org/g/(\d+)/", url)
    if m:
        p = Path(settings.data_gallery_path) / "ehentai" / m.group(1)
        return p if p.exists() else None

    m = re.search(r"pixiv\.net/.*?artworks?/(\d+)", url)
    if m:
        artwork_id = m.group(1)
        # Use os.scandir instead of glob — avoids building a full generator
        # of all artist subdirectories; scandir yields DirEntry objects with
        # cached stat data, making is_dir() free on Linux (d_type from readdir).
        pixiv_root = Path(settings.data_gallery_path) / "pixiv"
        if pixiv_root.is_dir():
            try:
                with os.scandir(pixiv_root) as it:
                    for entry in it:
                        if entry.is_dir():
                            candidate = Path(entry.path) / artwork_id
                            if candidate.exists():
                                return candidate
            except OSError as exc:
                logger.warning("[download] scandir pixiv root failed: %s", exc)
    return None


async def _set_job_status(job_id: str | None, status: str, error: str | None = None) -> None:
    if not job_id:
        return
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(DownloadJob, uuid.UUID(job_id))
            if job:
                job.status = status
                if error:
                    job.error = error
                # "paused" is an intermediate state — do not set finished_at
                if status in ("done", "failed", "cancelled"):
                    job.finished_at = datetime.now(UTC)
                await session.commit()
    except (sqlalchemy.exc.SQLAlchemyError, ValueError, OSError) as exc:
        logger.error("[download] failed to update job status: %s", exc)


async def _set_job_progress(job_id: str | None, progress: dict) -> None:
    """Persist progress JSONB to the DB without changing status or finished_at."""
    if not job_id:
        return
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(DownloadJob, uuid.UUID(job_id))
            if job:
                job.progress = progress
                await session.commit()
    except (sqlalchemy.exc.SQLAlchemyError, ValueError, OSError) as exc:
        logger.warning("[download] failed to update job progress: %s", exc)


# ── WORKER B: Import ─────────────────────────────────────────────────


async def import_job(ctx: dict, path: str, db_job_id: str | None = None) -> dict:
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
    for meta_file in sorted(gallery_path.glob("*.json")):
        try:
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            break
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            logger.warning("[import] failed to read metadata %s: %s", meta_file, exc)
            continue

    # Extract source from Category (gallery-dl uses this for the extractor name)
    source = metadata.get("category")
    if not source:
        # Fallback heuristic
        parts = gallery_path.parts
        if "ehentai" in parts:
            source = "ehentai"
        elif "pixiv" in parts:
            source = "pixiv"
        else:
            source = "gallery_dl"

    # Extract source ID
    source_id = str(metadata.get("gallery_id") or metadata.get("tweet_id") or metadata.get("id") or gallery_path.name)

    tags = _extract_tags(gallery_path, metadata)
    image_files = sorted(
        [f for f in gallery_path.iterdir() if f.suffix.lower() in _IMAGE_EXTS],
        key=lambda f: f.name,
    )

    if not image_files:
        return {"status": "failed", "error": "no images found"}

    import shutil as _shutil

    async with AsyncSessionLocal() as session:
        # Upsert gallery
        gallery_values = _build_gallery(source, source_id, metadata, tags, len(image_files))
        stmt = (
            pg_insert(Gallery)
            .values(**gallery_values)
            .on_conflict_do_update(
                index_elements=["source", "source_id"],
                set_={
                    "title": pg_insert(Gallery).excluded.title,
                    "tags_array": pg_insert(Gallery).excluded.tags_array,
                    "download_status": "complete",
                    "pages": pg_insert(Gallery).excluded.pages,
                },
            )
            .returning(Gallery.id)
        )
        gallery_id = (await session.execute(stmt)).scalar_one()

        # Compute hashes sequentially (avoid memory spikes for large galleries)
        hashes = await asyncio.gather(*[asyncio.to_thread(_sha256, f) for f in image_files])

        # Store each file in CAS and create library symlink
        for img_file, sha256 in zip(image_files, hashes, strict=False):
            blob = await store_blob(img_file, sha256, session)
            await asyncio.to_thread(create_library_symlink, gallery_id, img_file.name, blob)

        # Flush blob upserts before inserting images (FK: blob_sha256 → blobs.sha256)
        await session.flush()

        # Bulk-insert images
        image_values = [
            {
                "gallery_id": gallery_id,
                "page_num": page_num,
                "filename": img_file.name,
                "blob_sha256": sha256,
            }
            for page_num, (img_file, sha256) in enumerate(zip(image_files, hashes, strict=False), start=1)
        ]
        if image_values:
            img_stmt = pg_insert(Image).values(image_values).on_conflict_do_nothing()
            await session.execute(img_stmt)

        # Upsert tags + gallery_tags
        await _upsert_tags(session, gallery_id, tags)
        await session.commit()

    # Delete the temporary download directory
    try:
        _shutil.rmtree(str(gallery_path), ignore_errors=True)
    except Exception as exc:
        logger.warning("[import] failed to remove temp dir %s: %s", gallery_path, exc)

    logger.info("[import] gallery_id=%d source=%s/%s", gallery_id, source, source_id)

    # Trigger thumbnail generation
    await ctx["redis"].enqueue_job("thumbnail_job", gallery_id)
    if settings.tag_model_enabled:
        await ctx["redis"].enqueue_job("tag_job", gallery_id)
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

    return {
        "source": source,
        "source_id": source_id,
        "title": meta.get("title") or meta.get("title_en", ""),
        "title_jpn": meta.get("title_jpn") or meta.get("title_original") or "",
        "category": meta.get("category") or meta.get("type", ""),
        "language": meta.get("lang") or meta.get("language", ""),
        "pages": page_count,
        "posted_at": posted_at,
        "uploader": meta.get("uploader", ""),
        "download_status": "complete",
        "tags_array": tags,
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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


# ── WORKER B2: Local Import ──────────────────────────────────────────


async def local_import_job(ctx: dict, source_dir: str, mode: str, gallery_id: int) -> dict:
    """Import a local directory into the database with progress tracking."""
    import json as _json

    logger.info("[local_import] gallery_id=%d source=%s mode=%s", gallery_id, source_dir, mode)

    src_path = Path(source_dir)
    if not src_path.is_dir():
        return {"status": "failed", "error": f"not a directory: {source_dir}"}

    _SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".mp4", ".webm"}
    files = sorted([f for f in src_path.iterdir() if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS])

    if not files:
        return {"status": "failed", "error": "no supported files found"}

    total = len(files)
    processed = 0
    r = ctx["redis"]

    async with AsyncSessionLocal() as session:
        for idx, f in enumerate(files):
            sha256 = await asyncio.to_thread(_sha256, f)

            if mode == "copy":
                # Hardlink/copy into CAS; create library symlink
                blob = await store_blob(f, sha256, session)
            else:
                # Link mode: record external path, do not copy file
                blob = await store_blob(f, sha256, session, storage="external", external_path=str(f))

            await asyncio.to_thread(create_library_symlink, gallery_id, f.name, blob)

            # Flush blob upsert before inserting image (FK constraint)
            await session.flush()

            stmt = pg_insert(Image).values(
                gallery_id=gallery_id,
                page_num=idx + 1,
                filename=f.name,
                blob_sha256=sha256,
            ).on_conflict_do_nothing()
            await session.execute(stmt)

            processed += 1

            # Update progress every 5 files or proportionally for small batches
            update_every = max(1, min(5, total // 10))
            if processed % update_every == 0 or processed == total:
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

        await session.commit()

    # Write done state with short TTL so frontend can display completion
    await r.setex(
        f"import:progress:{gallery_id}",
        30,
        _json.dumps({"processed": processed, "total": total, "status": "done"}),
    )

    logger.info("[local_import] gallery_id=%d: %d files imported", gallery_id, processed)

    # Trigger thumbnail generation
    await ctx["redis"].enqueue_job("thumbnail_job", gallery_id)

    # Trigger AI tagging if enabled
    if settings.tag_model_enabled:
        await ctx["redis"].enqueue_job("tag_job", gallery_id)

    return {"status": "done", "processed": processed}


# ── WORKER B3: Rescan Library ────────────────────────────────────────


async def rescan_library_job(ctx: dict) -> dict:
    """
    Rescan all galleries in the database:
    - Verify image files still exist on disk; remove DB records for missing files.
    - Update gallery.pages to the actual file count.
    - Enqueue thumbnail_job for galleries with images that have no thumbnail.
    Progress is written to Redis key ``rescan:progress`` during the run and
    deleted on completion so the status endpoint can report accurately.
    """
    import json as _json

    logger.info("[rescan_library] starting full library rescan")
    r = ctx["redis"]

    # Pause watcher during full rescan to avoid duplicate triggers
    from core.watcher import watcher_instance as _wi
    _watcher_was_running = _wi is not None and _wi.is_running
    if _watcher_was_running:
        _wi.pause()

    total = 0
    cancelled = False
    try:
        async with AsyncSessionLocal() as session:
            # Order by last_scanned_at NULLS FIRST so unscanned galleries get priority
            gallery_rows = (await session.execute(
                select(Gallery).order_by(Gallery.last_scanned_at.asc().nulls_first())
            )).scalars().all()
            total = len(gallery_rows)
            logger.info("[rescan_library] %d galleries to scan", total)

            for idx, gallery in enumerate(gallery_rows):
                # Check for cancel signal before processing each gallery
                cancel_flag = await r.get("rescan:cancel")
                if cancel_flag:
                    await r.delete("rescan:cancel")
                    await r.setex(
                        "rescan:progress",
                        3600,
                        _json.dumps({"processed": idx, "total": total, "status": "cancelled"}),
                    )
                    logger.info("[rescan_library] cancelled at gallery %d/%d", idx, total)
                    cancelled = True
                    break

                await r.setex(
                    "rescan:progress",
                    3600,
                    _json.dumps({
                        "processed": idx,
                        "total": total,
                        "status": "running",
                        "current_gallery": gallery.id,
                    }),
                )

                import shutil
                from sqlalchemy.orm import selectinload
                images = (await session.execute(
                    select(Image).where(Image.gallery_id == gallery.id)
                    .options(selectinload(Image.blob))
                )).scalars().all()

                missing_thumb = False
                removed = 0
                for img in images:
                    blob = img.blob
                    if not blob:
                        await session.delete(img)
                        removed += 1
                        continue
                    src = resolve_blob_path(blob)
                    if not src.exists():
                        logger.warning(
                            "[rescan_library] gallery_id=%d image_id=%d missing file: %s",
                            gallery.id,
                            img.id,
                            str(src),
                        )
                        # Delete thumbnail directory before removing the DB record
                        td = thumb_dir(blob.sha256)
                        if td.exists():
                            shutil.rmtree(str(td), ignore_errors=True)
                        await decrement_ref_count(blob.sha256, session)
                        await session.delete(img)
                        removed += 1
                        continue
                    td = thumb_dir(blob.sha256)
                    if not (td / "thumb_160.webp").exists():
                        missing_thumb = True

                if removed:
                    await session.flush()
                    # Recount surviving images
                    surviving = (await session.execute(
                        select(Image).where(Image.gallery_id == gallery.id)
                        .options(selectinload(Image.blob))
                    )).scalars().all()
                    gallery.pages = len(surviving)
                    if gallery.pages == 0 and gallery.import_mode == "link":
                        # Clean up any remaining thumbnail dirs then delete the gallery entirely
                        remaining_imgs = (await session.execute(
                            select(Image).where(Image.gallery_id == gallery.id)
                            .options(selectinload(Image.blob))
                        )).scalars().all()
                        for rim in remaining_imgs:
                            if rim.blob:
                                td = thumb_dir(rim.blob.sha256)
                                if td.exists():
                                    shutil.rmtree(str(td), ignore_errors=True)
                                await decrement_ref_count(rim.blob.sha256, session)
                        await session.delete(gallery)
                        await session.commit()
                        logger.info(
                            "[rescan_library] gallery_id=%d removed (link mode, all files gone)",
                            gallery.id,
                        )
                        continue
                    elif gallery.pages == 0:
                        gallery.download_status = "missing"
                    logger.info(
                        "[rescan_library] gallery_id=%d: removed %d missing images, pages=%d",
                        gallery.id,
                        removed,
                        gallery.pages,
                    )

                if missing_thumb:
                    await r.enqueue_job("thumbnail_job", gallery.id)
                    logger.info(
                        "[rescan_library] gallery_id=%d: enqueued thumbnail_job (missing thumbs)",
                        gallery.id,
                    )

                gallery.last_scanned_at = datetime.now(timezone.utc)
                # Commit after each gallery so progress is persisted incrementally
                await session.commit()

    finally:
        # Always resume the watcher even if the scan fails or is cancelled
        if _watcher_was_running and _wi is not None:
            _wi.resume()

    if not cancelled:
        await r.setex(
            "rescan:progress",
            30,
            _json.dumps({"processed": total, "total": total, "status": "done"}),
        )
        logger.info("[rescan_library] completed, %d galleries processed", total)
    return {"status": "cancelled" if cancelled else "done", "total": total}


# ── WORKER B4: Rescan Gallery ─────────────────────────────────────────


async def rescan_gallery_job(ctx: dict, gallery_id: int) -> dict:
    """
    Rescan a single gallery:
    - Verify existing image files; remove DB records for files that have gone missing.
    - Scan the gallery directory for new files not yet in the DB and insert them.
    - Update gallery.pages and gallery.download_status.
    - Re-enqueue thumbnail_job if any thumbnails are absent.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert_local

    logger.info("[rescan_gallery] gallery_id=%d", gallery_id)

    async with AsyncSessionLocal() as session:
        gallery = await session.get(Gallery, gallery_id)
        if not gallery:
            logger.error("[rescan_gallery] gallery_id=%d not found", gallery_id)
            return {"status": "failed", "error": "gallery not found"}

        import shutil
        from sqlalchemy.orm import selectinload
        images = (await session.execute(
            select(Image).where(Image.gallery_id == gallery_id)
            .options(selectinload(Image.blob))
        )).scalars().all()

        # --- Step 1: Verify existing records ---
        known_sha256s: set[str] = set()
        missing_thumb = False
        removed = 0
        for img in images:
            blob = img.blob
            if not blob:
                await session.delete(img)
                removed += 1
                continue
            src = resolve_blob_path(blob)
            if not src.exists():
                logger.warning(
                    "[rescan_gallery] gallery_id=%d image_id=%d missing: %s",
                    gallery_id,
                    img.id,
                    str(src),
                )
                # Delete thumbnail directory before removing the DB record
                td = thumb_dir(blob.sha256)
                if td.exists():
                    shutil.rmtree(str(td), ignore_errors=True)
                await decrement_ref_count(blob.sha256, session)
                await session.delete(img)
                removed += 1
                continue
            known_sha256s.add(blob.sha256)
            td = thumb_dir(blob.sha256)
            if not (td / "thumb_160.webp").exists():
                missing_thumb = True

        if removed:
            await session.flush()

        # --- Step 2: Discover new files in the gallery directory ---
        # With CAS, the gallery directory is the library symlink directory.
        gallery_dir: Path | None = None
        surviving_images = (await session.execute(
            select(Image).where(Image.gallery_id == gallery_id)
            .options(selectinload(Image.blob))
        )).scalars().all()

        gallery_dir = library_dir(gallery_id)
        if not gallery_dir.exists():
            # Fallback: try source/source_id convention
            candidate = Path(settings.data_gallery_path) / gallery.source / gallery.source_id
            if candidate.is_dir():
                gallery_dir = candidate
            else:
                gallery_dir = None

        new_files_added = 0
        if gallery_dir and gallery_dir.is_dir():
            _SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"}
            # Determine the next page_num
            max_page = max((img.page_num for img in surviving_images), default=0)

            try:
                dir_files = sorted(
                    [f for f in gallery_dir.iterdir() if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS],
                    key=lambda f: f.name,
                )
            except OSError as exc:
                logger.warning("[rescan_gallery] gallery_id=%d failed to read dir: %s", gallery_id, exc)
                dir_files = []

            for fpath in dir_files:
                file_hash = await asyncio.to_thread(_sha256, fpath)
                if file_hash in known_sha256s:
                    continue
                # New file found on disk that is not in the DB.
                blob = await store_blob(fpath, file_hash, session)
                await create_library_symlink(gallery_id, fpath.name, blob)
                await session.flush()
                max_page += 1
                stmt = pg_insert_local(Image).values(
                    gallery_id=gallery_id,
                    page_num=max_page,
                    filename=fpath.name,
                    blob_sha256=file_hash,
                ).on_conflict_do_nothing()
                await session.execute(stmt)
                new_files_added += 1
                missing_thumb = True  # New file needs a thumbnail.
                known_sha256s.add(file_hash)
                logger.info(
                    "[rescan_gallery] gallery_id=%d: added new file %s",
                    gallery_id,
                    fpath.name,
                )

        # --- Step 3: Update gallery metadata ---
        final_images = (await session.execute(
            select(Image).where(Image.gallery_id == gallery_id)
            .options(selectinload(Image.blob))
        )).scalars().all()
        gallery.pages = len(final_images)

        if gallery.pages == 0 and gallery.import_mode == "link":
            # All source files are gone — clean up remaining thumbnail dirs and remove gallery
            remaining_imgs = (await session.execute(
                select(Image).where(Image.gallery_id == gallery_id)
                .options(selectinload(Image.blob))
            )).scalars().all()
            for rim in remaining_imgs:
                if rim.blob:
                    td = thumb_dir(rim.blob.sha256)
                    if td.exists():
                        shutil.rmtree(str(td), ignore_errors=True)
                    await decrement_ref_count(rim.blob.sha256, session)
            await session.delete(gallery)
            await session.commit()
            logger.info("[rescan_gallery] gallery_id=%d removed (link mode, all files gone)", gallery_id)
            return {"status": "removed", "gallery_id": gallery_id, "removed": removed, "added": 0, "pages": 0}

        if gallery.pages == 0:
            gallery.download_status = "missing"
        elif gallery.download_status == "missing":
            gallery.download_status = "complete"
        gallery.last_scanned_at = datetime.now(timezone.utc)

        await session.commit()

    if missing_thumb:
        await ctx["redis"].enqueue_job("thumbnail_job", gallery_id)
        logger.info("[rescan_gallery] gallery_id=%d: enqueued thumbnail_job", gallery_id)

    logger.info(
        "[rescan_gallery] gallery_id=%d done: removed=%d added=%d pages=%d",
        gallery_id,
        removed,
        new_files_added,
        gallery.pages,
    )
    return {
        "status": "done",
        "gallery_id": gallery_id,
        "removed": removed,
        "added": new_files_added,
        "pages": gallery.pages,
    }


# ── WORKER C: Tag ────────────────────────────────────────────────────


async def tag_job(ctx: dict, gallery_id: int) -> dict:
    """AI tagging via WD14 — tags all images in a gallery."""
    if not settings.tag_model_enabled:
        logger.info("[tag] gallery_id=%d skipped (TAG_MODEL_ENABLED=false)", gallery_id)
        return {"status": "skipped", "reason": "TAG_MODEL_ENABLED=false"}

    logger.info("[tag] gallery_id=%d", gallery_id)

    from sqlalchemy.orm import selectinload

    from services.tagger import predict

    tagged = 0
    async with AsyncSessionLocal() as session:
        images = (await session.execute(
            select(Image).where(Image.gallery_id == gallery_id)
            .options(selectinload(Image.blob))
        )).scalars().all()

        for img in images:
            blob = img.blob
            if not blob:
                continue
            src = resolve_blob_path(blob)
            if not src.exists() or src.suffix.lower() not in _IMAGE_EXTS:
                continue

            try:
                results = await asyncio.to_thread(
                    predict,
                    str(src),
                    settings.tag_general_threshold,
                    settings.tag_character_threshold,
                )
            except Exception as exc:
                logger.warning("[tag] image %d failed: %s", img.id, exc)
                continue

            if not results:
                continue

            # Build tag strings for tags_array
            tag_strings = [f"{ns}:{name}" for ns, name, _ in results]

            # Upsert tags to tags table and get IDs
            tag_values = [{"namespace": ns, "name": name, "count": 0} for ns, name, _ in results]
            if tag_values:
                tag_stmt = (
                    pg_insert(Tag)
                    .values(tag_values)
                    .on_conflict_do_nothing(index_elements=["namespace", "name"])
                    .returning(Tag.id, Tag.namespace, Tag.name)
                )
                tag_rows = (await session.execute(tag_stmt)).all()

                # For tags that already existed (on_conflict_do_nothing returns nothing for those),
                # we need to fetch their IDs separately
                existing_keys = {(r.namespace, r.name) for r in tag_rows}
                missing = [(ns, name) for ns, name, _ in results if (ns, name) not in existing_keys]

                tag_id_map: dict[tuple[str, str], int] = {(r.namespace, r.name): r.id for r in tag_rows}

                if missing:
                    for ns, name in missing:
                        row = (await session.execute(
                            select(Tag.id).where(Tag.namespace == ns, Tag.name == name)
                        )).scalar_one_or_none()
                        if row:
                            tag_id_map[(ns, name)] = row

                # Build confidence map
                conf_map = {(ns, name): conf for ns, name, conf in results}

                # Upsert image_tags
                from db.models import ImageTag
                it_values = []
                for (ns, name), tid in tag_id_map.items():
                    it_values.append({
                        "image_id": img.id,
                        "tag_id": tid,
                        "confidence": conf_map.get((ns, name)),
                    })

                if it_values:
                    it_stmt = (
                        pg_insert(ImageTag)
                        .values(it_values)
                        .on_conflict_do_update(
                            index_elements=["image_id", "tag_id"],
                            set_={"confidence": pg_insert(ImageTag).excluded.confidence},
                        )
                    )
                    await session.execute(it_stmt)

            # Update image's tags_array (merge with existing)
            existing_tags = set(img.tags_array or [])
            existing_tags.update(tag_strings)
            img.tags_array = list(existing_tags)

            tagged += 1

        await session.commit()

    logger.info("[tag] gallery_id=%d: %d images tagged", gallery_id, tagged)
    return {"status": "done", "tagged": tagged}


# ── WORKER D: Thumbnail ──────────────────────────────────────────────


async def thumbnail_job(ctx: dict, gallery_id: int) -> dict:
    """Generate 160/360/720px WebP thumbnails for all images in a gallery."""
    import imagehash
    from PIL import Image as PILImage
    from sqlalchemy.orm import selectinload

    logger.info("[thumbnail] gallery_id=%d", gallery_id)
    sizes = [160, 360, 720]
    processed = 0

    async with AsyncSessionLocal() as session:
        images = (
            await session.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id)
                .options(selectinload(Image.blob))
            )
        ).scalars().all()

        for img in images:
            blob = img.blob
            if not blob:
                continue
            src = resolve_blob_path(blob)
            if not src.exists():
                continue

            td = thumb_dir(blob.sha256)
            td.mkdir(parents=True, exist_ok=True)

            try:
                with PILImage.open(src) as pil:
                    # Store actual dimensions and phash on the blob
                    blob.width, blob.height = pil.size
                    blob.phash = str(imagehash.phash(pil))
                    rgb = pil.convert("RGB")
                    for size in sizes:
                        dest = td / f"thumb_{size}.webp"
                        if dest.exists():
                            continue
                        thumb = rgb.copy()
                        thumb.thumbnail((size, size * 2), PILImage.LANCZOS)
                        tmp = dest.with_suffix(".tmp")
                        thumb.save(str(tmp), "WEBP", quality=85)
                        os.rename(tmp, dest)

                processed += 1
            except (OSError, ValueError) as exc:
                logger.error("[thumbnail] %s: %s", src, exc)

        await session.commit()

    logger.info("[thumbnail] gallery_id=%d: %d done", gallery_id, processed)
    return {"status": "done", "processed": processed}


# ── WORKER I: Reconciliation + Blob GC ───────────────────────────────


async def reconciliation_job(ctx: dict) -> dict:
    """
    Reconcile /data/library/ symlink tree with database records.

    Users can delete symlinks directly from filesystem. This job syncs
    those changes back to the database.

    Also runs blob GC: removes unreferenced blobs and their CAS files.
    """
    import shutil
    from sqlalchemy.orm import selectinload

    logger.info("[reconcile] Starting reconciliation")
    r = ctx["redis"]

    # Check 14-day interval via Redis
    last_run_key = "reconcile:last_run"
    last_run = await r.get(last_run_key)
    if last_run:
        last_dt = datetime.fromisoformat(last_run.decode())
        if (datetime.now(UTC) - last_dt).days < 14:
            logger.info("[reconcile] Skipping — last run was %s (< 14 days ago)", last_run.decode())
            return {"status": "skipped", "reason": "interval_not_reached"}

    stats = {"removed_images": 0, "removed_galleries": 0, "orphan_blobs_cleaned": 0}

    lib_base = Path(settings.data_library_path)
    if not lib_base.exists():
        logger.info("[reconcile] library path does not exist, nothing to do")
        await r.set(last_run_key, datetime.now(UTC).isoformat())
        return {"status": "done", **stats}

    async with AsyncSessionLocal() as session:
        # Phase 1: Scan library directories and compare with DB
        for gallery_dir in sorted(lib_base.iterdir()):
            if not gallery_dir.is_dir():
                continue
            try:
                gallery_id = int(gallery_dir.name)
            except ValueError:
                logger.warning("[reconcile] skipping non-numeric dir: %s", gallery_dir.name)
                continue

            # Get DB images for this gallery
            db_images = (await session.execute(
                select(Image)
                .where(Image.gallery_id == gallery_id)
                .options(selectinload(Image.blob))
            )).scalars().all()

            db_filenames = {img.filename: img for img in db_images}

            # Check which symlinks exist on disk
            disk_files: set[str] = set()
            for entry in gallery_dir.iterdir():
                disk_files.add(entry.name)
                # Check for broken symlinks
                if entry.is_symlink() and not entry.exists():
                    # Broken symlink — remove it
                    entry.unlink()
                    if entry.name in db_filenames:
                        img = db_filenames[entry.name]
                        await decrement_ref_count(img.blob_sha256, session)
                        await session.delete(img)
                        stats["removed_images"] += 1

            # Check for DB records whose symlinks are missing
            for filename, img in db_filenames.items():
                if filename not in disk_files:
                    await decrement_ref_count(img.blob_sha256, session)
                    await session.delete(img)
                    stats["removed_images"] += 1

            # If gallery directory is now empty, remove gallery
            remaining = list(gallery_dir.iterdir())
            if not remaining:
                gallery = await session.get(Gallery, gallery_id)
                if gallery:
                    await session.delete(gallery)
                    stats["removed_galleries"] += 1
                try:
                    gallery_dir.rmdir()
                except OSError:
                    pass

        # Phase 2: Check for galleries in DB whose library directory doesn't exist
        # (Only check downloaded/imported galleries, not proxy_only)
        all_galleries = (await session.execute(
            select(Gallery).where(Gallery.download_status != "proxy_only")
        )).scalars().all()

        for g in all_galleries:
            gdir = lib_base / str(g.id)
            if not gdir.exists():
                # Library directory missing — get images and decrement ref counts
                images = (await session.execute(
                    select(Image).where(Image.gallery_id == g.id)
                )).scalars().all()
                for img in images:
                    await decrement_ref_count(img.blob_sha256, session)
                    stats["removed_images"] += 1
                await session.delete(g)
                stats["removed_galleries"] += 1

        await session.commit()

    # Phase 3: Blob GC — clean up unreferenced blobs
    async with AsyncSessionLocal() as session:
        from sqlalchemy import func as sqlfunc

        orphan_blobs = (await session.execute(
            select(Blob).where(Blob.ref_count <= 0)
        )).scalars().all()

        for blob in orphan_blobs:
            # Safety check: verify no images actually reference this blob
            actual_refs = (await session.execute(
                select(Image.id).where(Image.blob_sha256 == blob.sha256).limit(1)
            )).scalar_one_or_none()

            if actual_refs is not None:
                # ref_count drifted — fix it
                count_result = (await session.execute(
                    select(sqlfunc.count()).select_from(Image).where(Image.blob_sha256 == blob.sha256)
                )).scalar_one()
                blob.ref_count = count_result
                logger.warning("[reconcile] ref_count drift for %s: corrected to %d", blob.sha256[:12], count_result)
                continue

            # No references — safe to delete CAS file and thumbnail
            cas_file = cas_path(blob.sha256, blob.extension)
            if cas_file.exists():
                try:
                    cas_file.unlink()
                except OSError as exc:
                    logger.warning("[reconcile] failed to delete CAS file %s: %s", cas_file, exc)

            # Delete thumbnail directory
            td = thumb_dir(blob.sha256)
            if td.exists():
                shutil.rmtree(str(td), ignore_errors=True)

            await session.delete(blob)
            stats["orphan_blobs_cleaned"] += 1

        await session.commit()

    # Record last run time
    await r.set(last_run_key, datetime.now(UTC).isoformat())

    # Store result in Redis for API query (30-day TTL)
    await r.setex("reconcile:last_result", 86400 * 30, json.dumps({
        "completed_at": datetime.now(UTC).isoformat(),
        **stats,
    }))

    logger.info("[reconcile] done: %s", stats)
    return {"status": "done", **stats}


# ── WORKER E: Auto-Discovery ──────────────────────────────────────────

_SUPPORTED_MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".mp4", ".webm"}


async def auto_discover_job(ctx: dict) -> dict:
    """Scan all library paths recursively and auto-create galleries for undiscovered directories containing media files."""
    logger.info("[auto_discover] Starting auto-discovery")

    paths = await get_all_library_paths()

    discovered = 0
    async with AsyncSessionLocal() as session:
        # Get all existing source="local" galleries with their source_id and library_path
        existing_rows = (await session.execute(
            select(Gallery.source_id, Gallery.library_path).where(Gallery.source == "local")
        )).all()
        existing_set = {(row.source_id, row.library_path) for row in existing_rows}

        for lib_path in paths:
            lib_dir = Path(lib_path)
            if not lib_dir.is_dir():
                continue

            # Walk the directory tree recursively; os.walk is efficient for deep trees
            for dirpath, dirnames, filenames in os.walk(str(lib_dir)):
                # Skip hidden directories in-place so os.walk won't descend into them
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

                current = Path(dirpath)
                # Skip the library root itself — only subfolders are gallery candidates
                if current == lib_dir:
                    continue

                # Use path relative to the library root as source_id for uniqueness
                # (e.g. "artist/album" instead of just "album" to avoid collisions)
                try:
                    rel_path = str(current.relative_to(lib_dir))
                except ValueError:
                    continue

                if (rel_path, lib_path) in existing_set:
                    continue

                # Only create a gallery if the directory directly contains media files
                file_count = sum(
                    1 for f in filenames
                    if Path(f).suffix.lower() in _SUPPORTED_MEDIA_EXTS
                )
                if file_count == 0:
                    continue

                # Derive a human-readable title from the leaf directory name
                title = current.name

                result = await session.execute(
                    text(
                        "INSERT INTO galleries (source, source_id, title, library_path, download_status)"
                        " VALUES ('local', :source_id, :title, :lib_path, 'importing')"
                        " ON CONFLICT (source, source_id) DO NOTHING"
                        " RETURNING id"
                    ),
                    {"source_id": rel_path, "title": title, "lib_path": lib_path},
                )
                row = result.scalar_one_or_none()
                if row:
                    gallery_id = row
                    discovered += 1
                    logger.info("[auto_discover] New gallery: %s (%d files)", rel_path, file_count)
                    await ctx["redis"].enqueue_job("local_import_job", str(current), "link", gallery_id)

        await session.commit()

    logger.info("[auto_discover] Discovered %d new galleries", discovered)
    return {"discovered": discovered}


# ── WORKER F: Rescan by Path ──────────────────────────────────────────


async def rescan_by_path_job(ctx: dict, dir_path: str) -> dict:
    """Rescan the gallery whose files reside in dir_path."""
    # In CAS mode, /data/library/{gallery_id}/ is the gallery directory.
    lib_base = Path(settings.data_library_path)
    dir_p = Path(dir_path)

    gallery_id: int | None = None
    # Check if this path is a library directory (or inside one)
    try:
        rel = dir_p.relative_to(lib_base)
        # The first component should be the gallery_id
        gallery_id = int(rel.parts[0])
    except (ValueError, IndexError):
        pass

    if not gallery_id:
        # Try checking if it's a blob external path
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Image.gallery_id)
                .join(Blob, Image.blob_sha256 == Blob.sha256)
                .where(Blob.external_path.like(f"{dir_path}%"))
                .limit(1)
            )
            gallery_id = result.scalar_one_or_none()

    if gallery_id:
        return await rescan_gallery_job(ctx, gallery_id)

    # No existing gallery found — might be a new directory, trigger auto-discover
    await ctx["redis"].enqueue_job("auto_discover_job")
    return {"status": "no_gallery_found", "path": dir_path}


# ── WORKER F2: Rescan Library Path ───────────────────────────────────


async def rescan_library_path_job(ctx: dict, library_path: str) -> dict:
    """Rescan all galleries that belong to a specific library path."""
    import json as _json

    logger.info("[rescan_path] starting rescan for path: %s", library_path)
    r = ctx["redis"]

    async with AsyncSessionLocal() as session:
        # Find all galleries with this library_path or whose images are under this path
        gallery_rows = (await session.execute(
            select(Gallery).where(
                (Gallery.library_path == library_path) |
                (Gallery.source == "local")
            ).order_by(Gallery.id)
        )).scalars().all()

        # Filter to galleries actually under this path
        relevant = []
        for g in gallery_rows:
            if g.library_path == library_path:
                relevant.append(g)
            elif g.library_path is None and g.import_mode == "link":
                # Check if any blob has external_path under this library_path
                blob_row = (await session.execute(
                    select(Blob.external_path)
                    .join(Image, Image.blob_sha256 == Blob.sha256)
                    .where(Image.gallery_id == g.id, Blob.storage == "external")
                    .limit(1)
                )).scalar_one_or_none()
                if blob_row and blob_row.startswith(library_path):
                    relevant.append(g)

        total = len(relevant)
        logger.info("[rescan_path] %d galleries under %s", total, library_path)

    # Rescan each gallery using existing job logic
    for idx, gallery in enumerate(relevant):
        await r.setex("rescan:progress", 3600, _json.dumps({
            "processed": idx, "total": total, "status": "running",
            "current_gallery": gallery.id,
        }))
        await rescan_gallery_job(ctx, gallery.id)

    await r.setex("rescan:progress", 30, _json.dumps({
        "processed": total, "total": total, "status": "done",
    }))
    logger.info("[rescan_path] completed, %d galleries processed", total)
    return {"status": "done", "total": total}


# ── WORKER G: Scheduled Scan ──────────────────────────────────────────


async def scheduled_scan_job(ctx: dict) -> dict:
    """Scheduled library scan — checks Redis settings before running."""
    r = ctx["redis"]

    # Check if scheduled scanning is enabled
    enabled = await r.get("scan:schedule:enabled")
    if enabled == b"0":
        logger.debug("[scheduled_scan] Skipped — disabled")
        return {"status": "skipped", "reason": "disabled"}

    # Check interval — only run if enough time has passed
    interval_raw = await r.get("scan:schedule:interval_hours")
    interval_hours = int(interval_raw) if interval_raw else settings.library_scan_interval_hours

    last_run_raw = await r.get("scan:schedule:last_run")
    if last_run_raw:
        last_run = datetime.fromisoformat(last_run_raw.decode())
        elapsed = (datetime.now(timezone.utc) - last_run).total_seconds() / 3600
        if elapsed < interval_hours - 0.1:  # small tolerance
            logger.debug(
                "[scheduled_scan] Skipped — last run %.1fh ago, interval=%dh",
                elapsed,
                interval_hours,
            )
            return {"status": "skipped", "reason": "too_soon"}

    logger.info("[scheduled_scan] Starting scheduled library scan")
    await auto_discover_job(ctx)
    await rescan_library_job(ctx)

    # Record last run time
    await r.set("scan:schedule:last_run", datetime.now(timezone.utc).isoformat())

    logger.info("[scheduled_scan] Scheduled scan complete")
    return {"status": "done"}


# ── WORKER H: Toggle Watcher ──────────────────────────────────────────


async def toggle_watcher_job(ctx: dict, enabled: bool) -> dict:
    """Start or stop the file system watcher on behalf of the API.

    The API cannot directly touch the watchdog Observer because it lives in the
    worker process.  Instead the API enqueues this job so the worker acts on the
    desired state immediately.

    The ``watcher:enabled`` Redis key (already written by the API before
    enqueuing this job) serves as the durable record that ``startup()`` reads on
    the next worker restart.
    """
    r = ctx["redis"]
    if enabled:
        if _watcher.is_running:
            logger.info("[toggle_watcher] Already running — no-op")
            return {"status": "already_running"}

        paths = await get_all_library_paths()
        if not paths:
            logger.warning("[toggle_watcher] No library paths configured — cannot start watcher")
            await r.set("watcher:status", json.dumps({"running": False, "paths": []}))
            return {"status": "no_paths"}

        loop = asyncio.get_event_loop()
        arq_pool = ctx["redis"]

        def enqueue_sync(job_name: str, *args):
            asyncio.run_coroutine_threadsafe(
                arq_pool.enqueue_job(job_name, *args), loop
            )

        _watcher.start(paths, enqueue_sync)
        await r.set("watcher:status", json.dumps({"running": True, "paths": paths}))
        logger.info("[toggle_watcher] Started, watching %d path(s)", len(paths))
        return {"status": "started", "paths": paths}
    else:
        if not _watcher.is_running:
            logger.info("[toggle_watcher] Already stopped — no-op")
            await r.set("watcher:status", json.dumps({"running": False, "paths": []}))
            return {"status": "already_stopped"}

        _watcher.stop()
        await r.set("watcher:status", json.dumps({"running": False, "paths": []}))
        logger.info("[toggle_watcher] Stopped")
        return {"status": "stopped"}


# ── ARQ Worker Settings ──────────────────────────────────────────────


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [
        download_job,
        import_job,
        local_import_job,
        rescan_library_job,
        rescan_gallery_job,
        rescan_by_path_job,
        rescan_library_path_job,
        auto_discover_job,
        tag_job,
        thumbnail_job,
        reconciliation_job,
        scheduled_scan_job,
        toggle_watcher_job,
    ]
    cron_jobs = [
        cron(
            scheduled_scan_job,
            hour=None,   # every hour
            minute=0,    # at :00
            run_at_startup=False,
            unique=True,
            timeout=7200,
        ),
        cron(
            reconciliation_job,
            weekday=0,   # Monday
            hour=3,
            minute=0,
            unique=True,
            timeout=3600,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = int(os.environ.get("MAX_WORKER_JOBS", "8"))
    job_timeout = 3600
