"""Preparation helpers for monitored library path moves."""

import os
from dataclasses import dataclass
from pathlib import Path

from db.models import Gallery, Image
from services.cas import OWNER_MARKER_FILENAME, create_library_symlink, library_dir


class _LibraryMoveConflict(RuntimeError):
    """A monitored move cannot be applied without risking gallery identity."""


@dataclass
class _LibraryMoveFilesystemState:
    old_dir: Path
    new_dir: Path
    renamed: bool
    created: bool
    marker_before: str | None
    links_before: dict[Path, str | None]

    def rollback(self) -> None:
        """Restore only filesystem artifacts changed by this move."""
        for link, target in reversed(tuple(self.links_before.items())):
            if os.path.lexists(link):
                link.unlink()
            if target is not None:
                link.symlink_to(target)

        marker = self.new_dir / OWNER_MARKER_FILENAME
        if self.marker_before is None:
            marker.unlink(missing_ok=True)
        else:
            marker.write_text(self.marker_before, encoding="utf-8")

        if self.renamed:
            if self.old_dir.exists():
                raise _LibraryMoveConflict(f"cannot roll back library move; old directory exists: {self.old_dir}")
            self.new_dir.rename(self.old_dir)
        elif self.created:
            self.new_dir.rmdir()


def _read_owner_marker(directory: Path) -> str | None:
    marker = directory / OWNER_MARKER_FILENAME
    try:
        return marker.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _LibraryMoveConflict(f"cannot read gallery ownership marker {marker}: {exc}") from exc


async def _prepare_library_move(
    gallery: Gallery,
    new_source_id: str,
    images: list[Image],
    new_external_paths: dict[int, str],
) -> _LibraryMoveFilesystemState:
    """Prepare library links before committing a monitored source move."""
    old_dir = library_dir(gallery.source, gallery.source_id)
    new_dir = library_dir(gallery.source, new_source_id)
    old_owner = f"{gallery.source}:{gallery.source_id}"
    new_owner = f"{gallery.source}:{new_source_id}"
    renamed = False
    created = False
    marker_before: str | None

    if old_dir.exists():
        if not old_dir.is_dir():
            raise _LibraryMoveConflict(f"gallery library path is not a directory: {old_dir}")
        old_marker = _read_owner_marker(old_dir)
        if old_marker not in (None, old_owner):
            raise _LibraryMoveConflict(
                f"gallery library directory {old_dir} is owned by {old_marker!r}, expected {old_owner!r}"
            )
        marker_before = old_marker
        if old_dir != new_dir:
            if os.path.lexists(new_dir):
                raise _LibraryMoveConflict(f"destination library directory already exists: {new_dir}")
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            old_dir.rename(new_dir)
            renamed = True
    elif not new_dir.exists():
        new_dir.mkdir(parents=True, exist_ok=False)
        created = True
        marker_before = None
    elif not new_dir.is_dir():
        raise _LibraryMoveConflict(f"destination library path is not a directory: {new_dir}")
    else:
        marker_before = _read_owner_marker(new_dir)

    if not renamed and marker_before not in (None, old_owner, new_owner):
        raise _LibraryMoveConflict(
            f"destination library directory {new_dir} is owned by {marker_before!r}, expected {new_owner!r}"
        )

    state = _LibraryMoveFilesystemState(
        old_dir=old_dir,
        new_dir=new_dir,
        renamed=renamed,
        created=created,
        marker_before=marker_before,
        links_before={},
    )
    try:
        (new_dir / OWNER_MARKER_FILENAME).write_text(new_owner, encoding="utf-8")
        for image in images:
            if not image.filename or Path(image.filename).name != image.filename:
                raise _LibraryMoveConflict(f"image {image.id} has an unsafe filename: {image.filename!r}")
            if image.blob is None and not new_external_paths.get(image.id):
                # A pending link page has no blob by design; it is only
                # linkable through its (moved) external path.
                raise _LibraryMoveConflict(f"image {image.id} has no blob")

            link = new_dir / image.filename
            if os.path.lexists(link):
                if not link.is_symlink():
                    raise _LibraryMoveConflict(f"refusing to replace non-symlink library artifact: {link}")
                state.links_before[link] = os.readlink(link)
            else:
                state.links_before[link] = None

            await create_library_symlink(
                gallery.source,
                new_source_id,
                image.filename,
                image.blob,
                external_path=new_external_paths.get(image.id),
            )
    except Exception:
        state.rollback()
        raise
    return state
