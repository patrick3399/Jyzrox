"""Filesystem access for the novel module — all path-traversal guards live here.

Only `.md` files strictly inside the repo root are ever exposed. Resolution is
symlink-aware: the resolved real path must remain within the resolved root.
"""

from __future__ import annotations

from pathlib import Path


class NovelPathError(Exception):
    """Raised when a requested path is outside the repo or not an allowed file."""


def safe_repo_path(repo_root: str | Path, rel_path: str) -> Path:
    if not rel_path or rel_path.startswith("/"):
        raise NovelPathError(f"invalid path: {rel_path!r}")
    root = Path(repo_root).resolve()
    candidate = (root / rel_path).resolve()
    if candidate.suffix != ".md":
        raise NovelPathError(f"not a markdown file: {rel_path!r}")
    if root not in candidate.parents and candidate != root:
        raise NovelPathError(f"path escapes repo root: {rel_path!r}")
    return candidate
