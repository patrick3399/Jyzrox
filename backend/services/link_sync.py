"""Incremental filesystem → DB sync for link-mode galleries (ADR 0014).

A link gallery's bytes stay in the user's folder, so the folder decides which
pages exist. Reconciling the two is cheap:

1. one ``stat`` of the source directory — an unchanged mtime means nothing was
   added, removed or renamed, and the gallery opens straight from the DB;
2. otherwise ``scandir`` + per-file ``stat`` against the size/mtime fingerprint
   stored on each Image row, hashing only files that are new or changed.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from services.media_formats import MEDIA_EXTENSIONS

logger = logging.getLogger(__name__)

# A file modified this recently may still be mid-copy; leave it for the next sync.
SETTLE_NS = 2_000_000_000

_NATURAL_SORT_RE = re.compile(r"(\d+)")


@dataclass(frozen=True, slots=True)
class FileStat:
    """One media file found in a source directory."""

    path: str
    name: str
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class KnownImage:
    """The DB's view of one link-mode page."""

    image_id: int
    external_path: str
    sha256: str
    size: int | None
    mtime_ns: int | None


@dataclass(slots=True)
class LinkSyncPlan:
    """What a sync has to do, decided from stat data alone."""

    unchanged: list[KnownImage] = field(default_factory=list)
    adopt: list[tuple[KnownImage, FileStat]] = field(default_factory=list)
    changed: list[tuple[KnownImage, FileStat]] = field(default_factory=list)
    new: list[FileStat] = field(default_factory=list)
    missing: list[KnownImage] = field(default_factory=list)
    unsettled: list[FileStat] = field(default_factory=list)

    @property
    def needs_hash(self) -> list[FileStat]:
        return [*self.new, *(file for _, file in self.changed)]


def _natural_sort_key(name: str) -> tuple[tuple[int, str | int], ...]:
    """Human page order: 1, 2, 10 instead of 1, 10, 2."""
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold()) for part in _NATURAL_SORT_RE.split(name))


def plan_link_sync(known: Iterable[KnownImage], files: Iterable[FileStat], *, now_ns: int) -> LinkSyncPlan:
    """Classify every file and every known page without reading file contents."""
    known = list(known)
    by_path = {image.external_path: image for image in known}
    plan = LinkSyncPlan()
    seen: set[str] = set()

    for file in sorted(files, key=lambda item: _natural_sort_key(item.name)):
        seen.add(file.path)
        image = by_path.get(file.path)
        settled = now_ns - file.mtime_ns >= SETTLE_NS
        if image is None:
            (plan.new if settled else plan.unsettled).append(file)
        elif image.size is None or image.mtime_ns is None:
            # Row predates fingerprints: trust the bytes, record the stat.
            plan.adopt.append((image, file))
        elif (image.size, image.mtime_ns) == (file.size, file.mtime_ns):
            plan.unchanged.append(image)
        elif settled:
            plan.changed.append((image, file))
        else:
            plan.unsettled.append(file)

    plan.missing = [image for image in known if image.external_path not in seen]
    return plan


def scan_media_files(directory: Path) -> list[FileStat]:
    """List the media files directly inside ``directory`` with their stat."""
    files: list[FileStat] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if Path(entry.name).suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            try:
                if not entry.is_file():
                    continue
                stat = entry.stat()
            except OSError:
                continue
            files.append(FileStat(path=entry.path, name=entry.name, size=stat.st_size, mtime_ns=stat.st_mtime_ns))
    return files


def library_root_available(root: str | None) -> bool:
    """Return False when a library root is missing or empty.

    An unmounted volume shows up as an absent path or an empty mount point. In
    that state every link file looks deleted, so callers must not remove rows.
    """
    if not root:
        return True
    try:
        with os.scandir(root) as entries:
            return next(entries, None) is not None
    except OSError:
        return False
