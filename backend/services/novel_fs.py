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
# Directories holding worldview/entity notes rather than chapters. Excluded from
# chapter listings and treated as the knowledge-index note corpus (Phase 1).
_NOTE_DIRS = {"Setting", "設定"}
_H1 = re.compile(r"^#\s+(.*)$", re.MULTILINE)

# Canon layout (Phase 1.5, spec 2026-07-08): category is derived purely from
# the path. Folder-name matching is case-insensitive; legacy names (Old, DEMO,
# extend) map to standard categories without moving any files.
_CATEGORY_DIRS = {
    "setting": "setting",
    "設定": "setting",
    "參考": "reference",
    "草稿": "draft",
    "廢案": "scrap",
    "番外": "extra",
    # legacy aliases found in the corpus
    "old": "scrap",
    "demo": "draft",
    "extend": "draft",
}
# Work-root files that are not chapters.
_SPECIAL_ROOT_FILES = {"setting.md": "setting", "format.md": "reference"}


class NovelPathError(Exception):
    """Raised when a requested path is outside the repo or not an allowed file."""


def classify_path(rel_path: str | Path) -> str:
    """Category of a repo-relative `.md` path: main | extra | draft |
    reference | scrap | setting. First matching directory (walking down from
    the work root) decides; the whole subtree inherits it. Unknown subdirs are
    'reference' so nothing is ever silently promoted to main."""
    parts = Path(rel_path).parts
    if len(parts) < 2:
        return "reference"  # repo-root file, not part of any work
    dirs = parts[1:-1]
    if not dirs:
        return _SPECIAL_ROOT_FILES.get(parts[-1].lower(), "main")
    for d in dirs:
        cat = _CATEGORY_DIRS.get(d.lower())
        if cat:
            return cat
    return "reference"


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
        count = sum(1 for f in entry.glob("*.md") if classify_path(f.relative_to(root)) == "main")
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
    for f in sorted(work_dir.glob("*.md"), key=lambda p: p.name):
        rel = f.relative_to(root)
        # Main text lives at the work root's first level only (spec §3 rule 4).
        if classify_path(rel) != "main":
            continue
        stat = f.stat()
        chapters.append(
            {
                "path": str(rel),
                "name": f.stem,
                "chars": stat.st_size,
                "mtime": stat.st_mtime,
                "category": "main",
            }
        )
    return chapters


def _note_title(text: str, stem: str) -> str:
    m = _H1.search(text)
    return m.group(1).strip() if m else stem


def list_notes(repo_root: str | Path) -> list[dict]:
    """Every `.md` under a Setting/設定 dir — the worldview/entity note corpus.

    title = first `# ` heading, else filename stem. Hidden dirs (.git) skipped.
    """
    root = Path(repo_root).resolve()
    notes: list[dict] = []
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if not any(part in _NOTE_DIRS for part in rel.parts):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:  # noqa: S112 — unreadable/binary file, skip silently
            continue
        notes.append({"path": str(rel), "work": rel.parts[0], "title": _note_title(text, f.stem)})
    return notes


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split leading YAML frontmatter from the markdown body.

    Tolerant by design (§4.5.8): no fence → ({}, content); malformed YAML →
    ({}, body). Never raises — old notes without frontmatter must index cleanly.
    """
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---", 4)
    if end == -1:
        return {}, content
    raw = content[4:end]
    body = content[end + 4 :].lstrip("\n")
    try:
        import yaml

        data = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001 — malformed frontmatter is tolerated
        return {}, body
    return (data if isinstance(data, dict) else {}), body


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
