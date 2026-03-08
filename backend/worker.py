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
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import sqlalchemy.exc
from arq.connections import RedisSettings
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

from core.config import settings
from core.database import AsyncSessionLocal
from core.redis_client import DownloadSemaphore, close_redis, init_redis
from db.models import DownloadJob, Gallery, GalleryTag, Image, Tag
from services.credential import get_credential
from services.eh_client import _GALLERY_URL_RE as EH_GALLERY_URL_RE
from services.eh_downloader import download_eh_gallery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"}


# ── Lifecycle ────────────────────────────────────────────────────────


async def startup(ctx: dict) -> None:
    logger.info("ARQ Worker started — Jyzrox")
    await init_redis()
    r = ctx["redis"]
    for key in ("download:sem:ehentai", "download:sem:pixiv", "download:sem:other"):
        await r.delete(key)


async def shutdown(ctx: dict) -> None:
    logger.info("ARQ Worker shutting down")
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

    # Validate URL domain
    allowed_domains = {
        "e-hentai.org", "exhentai.org",
        "www.pixiv.net", "pixiv.net",
        "danbooru.donmai.us",
        "twitter.com", "x.com",
    }
    try:
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        if not any(domain == d or domain.endswith("." + d) for d in allowed_domains):
            err = f"Unsupported domain: {domain}"
            logger.warning("[download] %s", err)
            await _set_job_status(db_job_id, "failed", err)
            return {"status": "failed", "error": err}
    except Exception:
        err = "Invalid URL format"
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

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
        cmd = [
            "gallery-dl",
            "--config-ignore",
            "--config",
            settings.gallery_dl_config,
            "--write-metadata",
            "--write-tags",
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
        except asyncio.TimeoutError:
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

        # Trigger import for detected gallery directory
        gallery_dir = _resolve_gallery_dir(url)
        if gallery_dir:
            await ctx["redis"].enqueue_job("import_job", str(gallery_dir), db_job_id)

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

    Path(settings.gallery_dl_config).write_text(json.dumps(config, indent=2))


def _detect_source(url: str) -> str:
    """Detect download source from URL for semaphore selection."""
    if "e-hentai.org" in url or "exhentai.org" in url:
        return "ehentai"
    if "pixiv.net" in url:
        return "pixiv"
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

    # Detect source from path
    parts = gallery_path.parts
    if "ehentai" in parts:
        source, source_id = "ehentai", gallery_path.name
    elif "pixiv" in parts:
        source, source_id = "pixiv", gallery_path.name
    else:
        source, source_id = "import", gallery_path.name

    # Read gallery-dl metadata (any .json file, they all have gallery info)
    metadata: dict = {}
    for meta_file in sorted(gallery_path.glob("*.json")):
        try:
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            break
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            logger.warning("[import] failed to read metadata %s: %s", meta_file, exc)
            continue

    tags = _extract_tags(gallery_path, metadata)
    image_files = sorted(
        [f for f in gallery_path.iterdir() if f.suffix.lower() in _IMAGE_EXTS],
        key=lambda f: f.name,
    )

    if not image_files:
        return {"status": "failed", "error": "no images found"}

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

        # Compute hashes concurrently, then bulk-insert all images in one statement
        hashes = await asyncio.gather(*[asyncio.to_thread(_sha256, f) for f in image_files])
        image_values = [
            {
                "gallery_id": gallery_id,
                "page_num": page_num,
                "filename": img_file.name,
                "file_path": str(img_file),
                "file_size": img_file.stat().st_size,
                "file_hash": file_hash,
            }
            for page_num, (img_file, file_hash) in enumerate(zip(image_files, hashes, strict=False), start=1)
        ]
        if image_values:
            img_stmt = pg_insert(Image).values(image_values).on_conflict_do_nothing()
            await session.execute(img_stmt)

        # Upsert tags + gallery_tags
        await _upsert_tags(session, gallery_id, tags)
        await session.commit()

    logger.info("[import] gallery_id=%d source=%s/%s", gallery_id, source, source_id)

    # Trigger thumbnail generation
    await ctx["redis"].enqueue_job("thumbnail_job", gallery_id)
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


# ── WORKER C: Tag (stub) ─────────────────────────────────────────────


async def tag_job(ctx: dict, image_id: int, image_path: str) -> dict:
    """AI tagging via WD14 — disabled until Phase 6 (TAG_MODEL_ENABLED=true)."""
    logger.info("[tag] image_id=%d skipped (TAG_MODEL_ENABLED=false)", image_id)
    return {"status": "skipped", "reason": "TAG_MODEL_ENABLED=false"}


# ── WORKER D: Thumbnail ──────────────────────────────────────────────


async def thumbnail_job(ctx: dict, gallery_id: int) -> dict:
    """Generate 160/360/720px WebP thumbnails for all images in a gallery."""
    from PIL import Image as PILImage

    logger.info("[thumbnail] gallery_id=%d", gallery_id)
    thumbs_root = Path(settings.data_thumbs_path)
    sizes = [160, 360, 720]
    processed = 0

    async with AsyncSessionLocal() as session:
        images = (await session.execute(select(Image).where(Image.gallery_id == gallery_id))).scalars().all()

        for img in images:
            if not img.file_path:
                continue
            src = Path(img.file_path)
            if not src.exists():
                continue

            # Ensure hash
            if not img.file_hash:
                img.file_hash = await asyncio.to_thread(_sha256, src)
            h = img.file_hash

            thumb_dir = thumbs_root / h[:2] / h
            thumb_dir.mkdir(parents=True, exist_ok=True)

            try:
                with PILImage.open(src) as pil:
                    # Store actual dimensions
                    img.width, img.height = pil.size
                    rgb = pil.convert("RGB")
                    for size in sizes:
                        dest = thumb_dir / f"thumb_{size}.webp"
                        if dest.exists():
                            continue
                        thumb = rgb.copy()
                        thumb.thumbnail((size, size * 2), PILImage.LANCZOS)
                        thumb.save(str(dest), "WEBP", quality=85)

                img.thumb_path = str(thumb_dir / "thumb_160.webp")
                processed += 1
            except (OSError, ValueError) as exc:
                logger.error("[thumbnail] %s: %s", src, exc)

        await session.commit()

    logger.info("[thumbnail] gallery_id=%d: %d done", gallery_id, processed)
    return {"status": "done", "processed": processed}


# ── ARQ Worker Settings ──────────────────────────────────────────────


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [download_job, import_job, tag_job, thumbnail_job]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 8
    job_timeout = 3600
