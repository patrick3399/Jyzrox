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
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy.exc

from arq.connections import RedisSettings
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import select

from core.config import settings
from core.database import AsyncSessionLocal
from db.models import DownloadJob, Gallery, GalleryTag, Image, Tag
from services.credential import get_credential

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"}


# ── Lifecycle ────────────────────────────────────────────────────────

async def startup(ctx: dict) -> None:
    logger.info("ARQ Worker started — Jyzrox")


async def shutdown(ctx: dict) -> None:
    logger.info("ARQ Worker shutting down")


# ── WORKER A: Download ───────────────────────────────────────────────

async def download_job(
    ctx: dict,
    url: str,
    source: str = "",
    options: dict | None = None,
    db_job_id: str | None = None,
) -> dict:
    """Download a gallery via gallery-dl, then enqueue import."""
    logger.info("[download] url=%s", url)

    await _set_job_status(db_job_id, "running")

    # Pre-flight: check credentials for the source
    cred_error = await _check_credentials(url)
    if cred_error:
        logger.error("[download] %s", cred_error)
        await _set_job_status(db_job_id, "failed", cred_error)
        return {"status": "failed", "error": cred_error}

    cmd = [
        "gallery-dl",
        "--config", settings.gallery_dl_config,
        "--write-metadata",
        "--write-tags",
        url,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        logger.error("[download] timeout: %s", url)
        await _set_job_status(db_job_id, "failed", "download timeout after 3600s")
        return {"status": "failed", "error": "timeout"}

    if proc.returncode != 0:
        err = proc.stderr[:500]
        logger.error("[download] gallery-dl error:\n%s", proc.stderr)
        await _set_job_status(db_job_id, "failed", err)
        return {"status": "failed", "error": err}

    logger.info("[download] done: %s", url)

    # Trigger import for detected gallery directory
    gallery_dir = _resolve_gallery_dir(url)
    if gallery_dir:
        await ctx["redis"].enqueue_job("import_job", str(gallery_dir), db_job_id)

    await _set_job_status(db_job_id, "done")
    return {"status": "done"}


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


def _resolve_gallery_dir(url: str) -> Path | None:
    """Guess the gallery directory path from the URL."""
    m = re.search(r"e[x\-]hentai\.org/g/(\d+)/", url)
    if m:
        p = Path(settings.data_gallery_path) / "ehentai" / m.group(1)
        return p if p.exists() else None

    m = re.search(r"pixiv\.net/.*?artworks?/(\d+)", url)
    if m:
        # Pixiv galleries are nested under artist dirs; scan for a matching subdir
        for artist_dir in Path(settings.data_gallery_path).glob("pixiv/*/"):
            candidate = artist_dir / m.group(1)
            if candidate.exists():
                return candidate
    return None


async def _set_job_status(
    job_id: str | None, status: str, error: str | None = None
) -> None:
    if not job_id:
        return
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(DownloadJob, uuid.UUID(job_id))
            if job:
                job.status = status
                if error:
                    job.error = error
                if status in ("done", "failed", "cancelled"):
                    job.finished_at = datetime.now(timezone.utc)
                await session.commit()
    except (sqlalchemy.exc.SQLAlchemyError, ValueError, OSError) as exc:
        logger.error("[download] failed to update job status: %s", exc)


# ── WORKER B: Import ─────────────────────────────────────────────────

async def import_job(
    ctx: dict, path: str, db_job_id: str | None = None
) -> dict:
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
                    "title":           pg_insert(Gallery).excluded.title,
                    "tags_array":      pg_insert(Gallery).excluded.tags_array,
                    "download_status": "complete",
                    "pages":           pg_insert(Gallery).excluded.pages,
                },
            )
            .returning(Gallery.id)
        )
        gallery_id = (await session.execute(stmt)).scalar_one()

        # Upsert images
        for page_num, img_file in enumerate(image_files, start=1):
            file_hash = await asyncio.to_thread(_sha256, img_file)
            img_stmt = (
                pg_insert(Image)
                .values(
                    gallery_id=gallery_id,
                    page_num=page_num,
                    filename=img_file.name,
                    file_path=str(img_file),
                    file_size=img_file.stat().st_size,
                    file_hash=file_hash,
                )
                .on_conflict_do_nothing()
            )
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
            if isinstance(raw_date, (int, float)):
                posted_at = datetime.fromtimestamp(raw_date, tz=timezone.utc)
            else:
                posted_at = datetime.fromisoformat(str(raw_date))
        except (ValueError, TypeError, OverflowError) as exc:
            logger.warning("[import] failed to parse date %r: %s", raw_date, exc)

    return {
        "source":          source,
        "source_id":       source_id,
        "title":           meta.get("title") or meta.get("title_en", ""),
        "title_jpn":       meta.get("title_jpn") or meta.get("title_original") or "",
        "category":        meta.get("category") or meta.get("type", ""),
        "language":        meta.get("lang") or meta.get("language", ""),
        "pages":           page_count,
        "posted_at":       posted_at,
        "uploader":        meta.get("uploader", ""),
        "download_status": "complete",
        "tags_array":      tags,
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


async def _upsert_tags(session, gallery_id: int, tags: list[str]) -> None:
    for tag_str in tags:
        if ":" in tag_str:
            ns, name = tag_str.split(":", 1)
        else:
            ns, name = "general", tag_str

        tag_stmt = (
            pg_insert(Tag)
            .values(namespace=ns, name=name, count=1)
            .on_conflict_do_update(
                index_elements=["namespace", "name"],
                set_={"count": Tag.count + 1},
            )
            .returning(Tag.id)
        )
        tag_id = (await session.execute(tag_stmt)).scalar_one()

        gt_stmt = (
            pg_insert(GalleryTag)
            .values(gallery_id=gallery_id, tag_id=tag_id, confidence=1.0, source="metadata")
            .on_conflict_do_nothing()
        )
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
        images = (
            await session.execute(select(Image).where(Image.gallery_id == gallery_id))
        ).scalars().all()

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
    max_jobs = 4
    job_timeout = 3600
