"""Library-symlink helpers for the link-gallery sync (ADR 0015)."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from services.cas import create_library_symlink, library_dir
from services.image_magic import validate_image_magic
from services.link_sync_plan import FileStat
from services.media_formats import VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)

LinkStates = list[tuple[Path, str | None]]


def _valid_media(files: list[FileStat]) -> list[FileStat]:
    """Drop image files whose bytes do not match their extension."""
    return [
        file
        for file in files
        if Path(file.name).suffix.lower() in VIDEO_EXTENSIONS or validate_image_magic(Path(file.path))
    ]


def _restore_links(states: LinkStates) -> None:
    """Undo symlinks created for rows that did not commit."""
    for link, previous_target in reversed(states):
        try:
            if link.is_symlink():
                link.unlink()
            if previous_target is not None:
                link.symlink_to(previous_target)
        except OSError as exc:
            logger.error("[link_sync] failed to restore library link %s: %s", link, exc)


async def _expose(source: str, source_id: str, filename: str, external_path: str, states: LinkStates) -> None:
    link = library_dir(source, source_id) / filename
    if link.exists() and not link.is_symlink():
        raise FileExistsError(f"refusing to replace non-symlink library file: {link}")
    states.append((link, os.readlink(link) if link.is_symlink() else None))
    await create_library_symlink(source, source_id, filename, None, external_path=external_path)


async def _commit(session, states: LinkStates) -> None:
    try:
        await session.commit()
    except Exception:
        _restore_links(states)
        raise
    states.clear()


@dataclass(slots=True)
class LinkSyncResult:
    status: str
    added: int = 0
    removed: int = 0
    renamed: int = 0
    # Pages reset to pending because their file changed.
    replaced: int = 0
    # Pending pages (no blob yet) after the sync.
    pending: int = 0
    pages: int | None = None
    # Files left out of this pass because they may still be being written.
    unsettled: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.renamed or self.replaced)

    def as_dict(self) -> dict:
        return {**asdict(self), "changed": self.changed}
