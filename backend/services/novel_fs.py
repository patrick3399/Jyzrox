"""Filesystem access for the novel module — all path-traversal guards live here.

Only `.md` files strictly inside the repo root are ever exposed. Resolution is
symlink-aware: the resolved real path must remain within the resolved root.
"""

from __future__ import annotations

import re
from pathlib import Path

_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
_ACT = re.compile(r"^### +(.*)$")
_RESERVED_DIRS = {"設定"}


class NovelPathError(Exception):
    """Raised when a requested path is outside the repo or not an allowed file."""


def safe_repo_path(repo_root: str | Path, rel_path: str) -> Path:
    if not rel_path or rel_path.startswith("/"):
        raise NovelPathError(f"invalid path: {rel_path!r}")
    root = Path(repo_root).resolve()
    # A null byte (or other OS-invalid path) makes resolve() raise ValueError;
    # surface it as NovelPathError so the router returns 400, not 500.
    try:
        candidate = (root / rel_path).resolve()
    except (ValueError, OSError) as e:
        raise NovelPathError(f"invalid path: {rel_path!r}") from e
    if candidate.suffix != ".md":
        raise NovelPathError(f"not a markdown file: {rel_path!r}")
    if root not in candidate.parents and candidate != root:
        raise NovelPathError(f"path escapes repo root: {rel_path!r}")
    return candidate


def list_works(repo_root: str | Path) -> list[dict]:
    root = Path(repo_root).resolve()
    works: list[dict] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name in _RESERVED_DIRS:
            continue
        count = sum(1 for _ in entry.rglob("*.md"))
        works.append({"name": entry.name, "chapter_count": count})
    return works


def list_chapters(repo_root: str | Path, work: str) -> list[dict]:
    root = Path(repo_root).resolve()
    try:
        work_dir = (root / work).resolve()
    except (ValueError, OSError) as e:
        raise NovelPathError(f"invalid work: {work!r}") from e
    if root not in work_dir.parents and work_dir != root:
        raise NovelPathError(f"work escapes repo root: {work!r}")
    chapters: list[dict] = []
    for f in sorted(work_dir.rglob("*.md"), key=lambda p: p.name):
        stat = f.stat()
        chapters.append(
            {
                "path": str(f.relative_to(root)),
                "name": f.stem,
                "chars": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )
    return chapters


def read_file(repo_root: str | Path, rel_path: str) -> str:
    return safe_repo_path(repo_root, rel_path).read_text(encoding="utf-8")


def file_exists(repo_root: str | Path, rel_path: str) -> bool:
    """Whether an allowed (`.md`, inside-root) file already exists at rel_path.

    Path validation runs first, so an unsafe path raises NovelPathError rather
    than silently reporting False — the create guard must not treat an escaping
    path as "free to write".
    """
    return safe_repo_path(repo_root, rel_path).exists()


def write_file(repo_root: str | Path, rel_path: str, content: str) -> None:
    path = safe_repo_path(repo_root, rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_acts(content: str) -> list[dict]:
    acts: list[dict] = []
    for lineno, line in enumerate(content.splitlines()):
        m = _ACT.match(line)
        if m:
            acts.append({"index": len(acts), "title": m.group(1).strip(), "line": lineno})
    return acts


def parse_backlinks(content: str) -> list[str]:
    seen: list[str] = []
    for m in _WIKILINK.finditer(content):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def keyword_scan(repo_root: str | Path, query: str, max_hits: int = 200) -> list[dict]:
    root = Path(repo_root).resolve()
    needle = query.lower()
    if not needle:
        return []
    hits: list[dict] = []
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root)
        # Skip repo-internal / hidden dirs (.git, etc.); 設定/ stays searchable.
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:  # noqa: S112 — unreadable/binary file, skip silently
            continue
        for lineno, line in enumerate(text.splitlines()):
            if needle in line.lower():
                hits.append({"path": str(f.relative_to(root)), "line": lineno, "text": line.strip()})
                if len(hits) >= max_hits:
                    return hits
    return hits
