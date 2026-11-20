"""Shared helpers for library scan jobs."""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.sql import select

from core.config import get_all_library_paths, get_monitored_library_paths, settings
from core.local_patterns import (
    DEFAULT_IMPORT_MODE,
    DEFAULT_LIBRARY_PATTERN,
    build_library_pattern_regex,
    normalize_relative_path,
)
from core.source_display import get_display_config
from db.models import Blob, Gallery, Image, LibraryPath
from services.cas import resolve_blob_path, thumb_dir, thumbnails_complete_at
from services.gallery_categories import resolve_category
from services.media_formats import MEDIA_EXTENSIONS as _SUPPORTED_MEDIA_EXTS
from worker.constants import logger


@dataclass(frozen=True)
class _LibrarySpec:
    path: str
    pattern: str = DEFAULT_LIBRARY_PATTERN
    import_mode: str = DEFAULT_IMPORT_MODE


@dataclass(frozen=True)
class _ImportRequest:
    gallery_id: int
    source_dir: str
    mode: str


def _cover_image_for_gallery(
    gallery: Gallery, images: list[Image], excluded_set: set[str] | None = None
) -> Image | None:
    excluded = excluded_set or set()
    eligible = []
    for img in images:
        visibility = getattr(img, "visibility", "active")
        if not isinstance(visibility, str):
            visibility = "active"
        if visibility != "active":
            continue
        if getattr(img, "blob_sha256", None) in excluded:
            continue
        eligible.append(img)
    if not eligible:
        return None
    ordered = sorted(eligible, key=lambda img: img.page_num)
    cfg = get_display_config(gallery.source or "")
    return ordered[-1] if cfg.cover_page == "last" else ordered[0]


def _has_thumb_160(blob: Blob) -> bool:
    return thumbnails_complete_at(thumb_dir(blob.sha256))


def _page_file_exists(img: Image) -> bool:
    if img.blob is None:
        return bool(img.external_path) and Path(img.external_path).exists()
    return resolve_blob_path(img.blob, img.external_path).exists()


def _probe_page(img: Image) -> tuple[bool, bool]:
    file_exists = _page_file_exists(img)
    return file_exists, file_exists and img.blob is not None and _has_thumb_160(img.blob)


async def _probe_pages(images: list[Image]) -> list[tuple[bool, bool]]:
    """Return (file exists, 160px thumbnail complete) for each image.

    The stats run in a thread: inline, one large gallery on the NFS data root
    stalled every other job sharing the worker's event loop.
    """
    return await asyncio.to_thread(lambda: [_probe_page(img) for img in images])


def _list_media_files(directory: Path) -> list[Path]:
    return [f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in _SUPPORTED_MEDIA_EXTS]


def _list_file_names(directory: Path) -> list[str]:
    return [entry.name for entry in directory.iterdir() if entry.is_file()]


def _walk_library_tree(root: str) -> list[tuple[str, list[str]]]:
    """Return (dirpath, filenames) for every non-hidden directory under root.

    Runs in a thread: the tree lives on the NFS data root, and walking it
    inline blocked every other job sharing the worker's event loop.
    """
    found: list[tuple[str, list[str]]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories in-place so os.walk won't descend into them
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        found.append((dirpath, filenames))
    return found


def _stat_and_list_media(directory: Path) -> tuple[os.stat_result, list[Path]]:
    return directory.stat(), _list_media_files(directory)


async def _get_library_specs(session, *, monitored_only: bool = False) -> list[_LibrarySpec]:
    filters = [LibraryPath.enabled == True]  # noqa: E712
    if monitored_only:
        filters.append(LibraryPath.monitor == True)  # noqa: E712
    rows = (await session.execute(select(LibraryPath).where(*filters))).scalars().all()
    specs = [
        _LibrarySpec(
            path=row.path,
            pattern=row.pattern or DEFAULT_LIBRARY_PATTERN,
            import_mode=row.import_mode or DEFAULT_IMPORT_MODE,
        )
        for row in rows
    ]
    seen = {spec.path for spec in specs}

    path_loader = get_monitored_library_paths if monitored_only else get_all_library_paths
    for path in await path_loader():
        if path not in seen:
            specs.append(_LibrarySpec(path=path))
            seen.add(path)
    return specs


async def _watcher_work_enabled(ctx: dict, watcher_origin: bool) -> bool:
    """Check whether a queued watcher-originated job should still start."""
    if not watcher_origin:
        return True
    enabled = await ctx["redis"].get("watcher:enabled")
    if enabled is None:
        return settings.library_monitor_enabled
    return enabled not in (b"0", "0")


def _media_count(filenames: list[str]) -> int:
    return sum(1 for f in filenames if Path(f).suffix.lower() in _SUPPORTED_MEDIA_EXTS)


async def _existing_local_status(session, rel_path: str) -> str | None:
    """Return the download_status of the local gallery at rel_path, if any."""
    return (
        await session.execute(
            select(Gallery.download_status).where(Gallery.source == "local", Gallery.source_id == rel_path)
        )
    ).scalar_one_or_none()


def _match_library_candidate(spec: _LibrarySpec, root: Path, candidate: Path) -> tuple[str, dict[str, str]] | None:
    try:
        rel_path = normalize_relative_path(str(candidate.relative_to(root)))
    except ValueError:
        return None
    match = build_library_pattern_regex(spec.pattern).match(rel_path)
    if not match:
        return None
    return rel_path, match.groupdict()


async def _discover_single_library_dir(session, spec: _LibrarySpec, current: Path) -> _ImportRequest | None:
    root = Path(spec.path)
    matched = _match_library_candidate(spec, root, current)
    if not matched:
        return None
    rel_path, groups = matched
    title = groups.get("title") or current.name
    artist = groups.get("artist")
    raw_category = groups.get("category")
    category = await resolve_category(session, raw_category)
    if raw_category and category is None:
        logger.warning(
            "[discover] %s: category folder %r is not in the category registry, importing without category",
            rel_path,
            raw_category,
        )
    source_path = os.path.realpath(current)

    # NOTE: the `WHERE galleries.deleted_at IS NULL` guard on the DO UPDATE
    # branch is required so this upsert never mutates/resurrects a trashed
    # gallery (HR-014). When the conflict target row is trashed, the WHERE
    # condition fails, no row is updated, and RETURNING yields nothing —
    # callers must treat a None result as "skip enqueue" (already the case
    # at all call sites).
    #
    # NOTE: `category` is deliberately absent from DO UPDATE SET. A path-derived
    # category is a first-import default, not a source of truth: re-discovery
    # must not clobber a value edited in the Workbench. Moving a gallery between
    # category folders therefore does not re-derive it (accepted trade-off).
    stmt = text(
        "INSERT INTO galleries "
        "(source, source_id, title, artist_id, uploader, category, library_path, source_path, import_mode, "
        "download_status) "
        "VALUES ('local', :source_id, :title, :artist_id, :uploader, :category, :library_path, :source_path, "
        ":import_mode, 'importing') "
        "ON CONFLICT (source, source_id) DO UPDATE SET "
        "title = EXCLUDED.title, "
        "artist_id = EXCLUDED.artist_id, "
        "uploader = EXCLUDED.uploader, "
        "library_path = EXCLUDED.library_path, "
        "source_path = EXCLUDED.source_path, "
        "import_mode = EXCLUDED.import_mode "
        "WHERE galleries.deleted_at IS NULL "
        "RETURNING id"
    )
    result = await session.execute(
        stmt,
        {
            "source_id": rel_path,
            "title": title,
            "artist_id": f"local:{artist}" if artist else None,
            "uploader": artist,
            "category": category,
            "library_path": spec.path,
            "source_path": source_path,
            "import_mode": spec.import_mode,
        },
    )
    gallery_id = result.scalar_one_or_none()
    if gallery_id is None:
        logger.debug(
            "[discover] skipping %s: upsert returned no row (likely conflicts with a trashed gallery)",
            rel_path,
        )
        return None
    return _ImportRequest(gallery_id=gallery_id, source_dir=source_path, mode=spec.import_mode)
