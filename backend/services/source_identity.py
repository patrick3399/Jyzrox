"""Stable filesystem identity checks for link-mode imports."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 65536


class SourceDirectoryChangedError(RuntimeError):
    """Raised when a pinned source path is renamed, replaced, or removed."""


class SourceFileChangedError(RuntimeError):
    """Raised when an individual source file is rewritten or replaced."""


@dataclass(frozen=True)
class SourceDirectoryIdentity:
    requested_path: str
    real_path: str
    device: int
    inode: int

    @classmethod
    def capture(cls, path: Path) -> SourceDirectoryIdentity:
        stat = path.stat()
        return cls(
            requested_path=str(path),
            real_path=os.path.realpath(path),
            device=stat.st_dev,
            inode=stat.st_ino,
        )

    def assert_unchanged(self, boundary: str) -> None:
        path = Path(self.requested_path)
        try:
            stat = path.stat()
            real_path = os.path.realpath(path)
        except OSError as exc:
            raise SourceDirectoryChangedError(
                f"source directory changed at {boundary}: {self.requested_path} is unavailable"
            ) from exc

        if stat.st_dev != self.device or stat.st_ino != self.inode or real_path != self.real_path:
            raise SourceDirectoryChangedError(
                f"source directory changed at {boundary}: expected {self.real_path} "
                f"({self.device}:{self.inode}), found {real_path} ({stat.st_dev}:{stat.st_ino})"
            )


@dataclass(frozen=True)
class SourceFileIdentity:
    """Identity of the exact bytes a hash was computed over."""

    path: str
    device: int
    inode: int
    size: int
    mtime_ns: int

    @classmethod
    def _from_stat(cls, path: Path, stat: os.stat_result) -> SourceFileIdentity:
        return cls(
            path=str(path),
            device=stat.st_dev,
            inode=stat.st_ino,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )

    def assert_unchanged(self, boundary: str) -> None:
        """Re-verify that the path still refers to the bytes we hashed."""
        try:
            stat = Path(self.path).stat()
        except OSError as exc:
            raise SourceFileChangedError(f"source file changed at {boundary}: {self.path} is unavailable") from exc
        current = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if current != (self.device, self.inode, self.size, self.mtime_ns):
            raise SourceFileChangedError(
                f"source file changed at {boundary}: {self.path} "
                f"expected {self.device}:{self.inode} size={self.size} mtime_ns={self.mtime_ns}, "
                f"found {stat.st_dev}:{stat.st_ino} size={stat.st_size} mtime_ns={stat.st_mtime_ns}"
            )


def hash_file_with_identity(path: Path) -> tuple[str, SourceFileIdentity]:
    """Return (sha256, identity) for the bytes actually read.

    The directory-level check cannot see this: replacing a file in place keeps
    the same name in the same directory, so the directory's inode is unchanged
    and every ``SourceDirectoryIdentity`` assertion still passes. Link-mode
    imports store the *path* rather than copying the bytes, so a replacement
    between hashing and commit would leave the DB recording a sha256 that no
    longer describes the file the row points at.

    Hashing through a single descriptor and fstat()ing that same descriptor is
    what makes the pair trustworthy — a bare stat() before or after the read may
    describe a different file. Two hazards are checked afterwards:

    * same inode, rewritten in place → size/mtime moved under us;
    * path re-pointed at a new inode → what we read is no longer what the path
      resolves to.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        before = os.fstat(handle.fileno())
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())

    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        raise SourceFileChangedError(
            f"source file changed while being hashed: {path} "
            f"size {before.st_size}→{after.st_size}, mtime_ns {before.st_mtime_ns}→{after.st_mtime_ns}"
        )

    try:
        current = path.stat()
    except OSError as exc:
        raise SourceFileChangedError(f"source file disappeared while being hashed: {path}") from exc
    if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
        raise SourceFileChangedError(
            f"source file replaced while being hashed: {path} "
            f"read {after.st_dev}:{after.st_ino}, path now resolves to {current.st_dev}:{current.st_ino}"
        )

    return digest.hexdigest(), SourceFileIdentity._from_stat(path, after)
