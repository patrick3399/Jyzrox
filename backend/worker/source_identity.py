"""Stable filesystem identity checks for link-mode imports."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class SourceDirectoryChangedError(RuntimeError):
    """Raised when a pinned source path is renamed, replaced, or removed."""


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
