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
_H1 = re.compile(r"^#\s+(.*)$", re.MULTILINE)
_WS = re.compile(r"\s+")

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


def _work_dir_of(repo_root: str | Path, work: str) -> tuple[Path, Path]:
    root = Path(repo_root).resolve()
    try:
        work_dir = (root / work).resolve()
    except ValueError as e:
        raise NovelPathError(f"invalid work: {work!r}") from e
    except OSError as e:
        raise NovelPathError(f"invalid work: {work!r}") from e
    if root not in work_dir.parents and work_dir != root:
        raise NovelPathError(f"work escapes repo root: {work!r}")
    return root, work_dir


def _file_record(root: Path, f: Path, category: str) -> dict:
    """Listing entry for one file: real character count + authored summary.

    `chars` is the whitespace-excluded character count of the body, NOT the byte
    size — CJK prose is ~3 bytes per character, so st_size was overstating every
    chapter threefold. Reading the file is what makes both fields possible; a
    per-work listing is a few dozen small files (measured: 17–77 ms for the real
    corpus's largest works).
    """
    stat = f.stat()
    try:
        text = f.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:  # unreadable/binary — list it, count nothing
        text = ""
    fm, body = parse_frontmatter(text)
    return {
        "path": str(f.relative_to(root)),
        "name": f.stem,
        "chars": len(_WS.sub("", body)),
        "summary": frontmatter_summary(fm),
        "mtime": stat.st_mtime,
        "category": category,
    }


def frontmatter_summary(fm: dict) -> str | None:
    """The `summary:` value as a trimmed one-liner, or None when absent/blank."""
    raw = fm.get("summary")
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    return text or None


def list_chapters(repo_root: str | Path, work: str) -> list[dict]:
    root, work_dir = _work_dir_of(repo_root, work)
    chapters: list[dict] = []
    for f in sorted(work_dir.glob("*.md"), key=lambda p: p.name):
        rel = f.relative_to(root)
        # Main text lives at the work root's first level only (spec §3 rule 4).
        if classify_path(rel) != "main":
            continue
        chapters.append(_file_record(root, f, "main"))
    return chapters


def list_work_files(repo_root: str | Path, work: str, category: str) -> list[dict]:
    """All `.md` files of one non-main category inside a work (spec §5.1)."""
    root, work_dir = _work_dir_of(repo_root, work)
    out: list[dict] = []
    for f in sorted(work_dir.rglob("*.md"), key=lambda p: str(p)):
        rel = f.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if classify_path(rel) != category:
            continue
        out.append(_file_record(root, f, category))
    return out


def count_work_files(repo_root: str | Path, work: str) -> dict[str, int]:
    """Per-category file counts (excluding main/setting) so the UI can hide
    empty sections without fetching each list."""
    root, work_dir = _work_dir_of(repo_root, work)
    counts = {"extra": 0, "draft": 0, "reference": 0, "scrap": 0}
    for f in work_dir.rglob("*.md"):
        rel = f.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        cat = classify_path(rel)
        if cat in counts:
            counts[cat] += 1
    return counts


def _note_title(text: str, stem: str) -> str:
    m = _H1.search(text)
    return m.group(1).strip() if m else stem


def list_notes(repo_root: str | Path) -> list[dict]:
    """Every `.md` classified as `setting` — the worldview/entity note corpus.

    Covers both the work-root `setting.md` and nested `Setting/`/`設定/` dirs
    (spec §3). title = first `# ` heading, else filename stem. Hidden dirs
    (.git) skipped.
    """
    root = Path(repo_root).resolve()
    notes: list[dict] = []
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if classify_path(rel) != "setting":
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


def _yaml_line(key: str, value: str) -> str:
    import yaml

    # width high enough that a long summary is never folded across lines: the
    # upsert below is line-oriented and a folded value would corrupt the fence.
    return yaml.safe_dump({key: value}, allow_unicode=True, width=10**6, sort_keys=False).rstrip("\n")


def _node_end(lines: list[str], start: int) -> int:
    """Index just past the top-level YAML node that begins at ``lines[start]``.

    A key's value is not always one line: block and folded scalars (`|`, `>`),
    multi-line flow collections, and wrapped quoted scalars all continue on
    more-indented lines. Removing only the `key:` line orphaned those
    continuations, and YAML then absorbed them into the *previous* key (silently
    rewriting it) or failed to parse the fence at all — in which case
    ``parse_frontmatter`` tolerates the error and returns ``{}``, losing every
    field without a word.

    Interior blank lines are claimed only when a further indented line follows,
    so a blank separating two top-level keys stays where the author put it.
    """
    i = start + 1
    claimed = i
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line[:1].isspace():
            i += 1
            claimed = i
            continue
        break
    return claimed


def set_frontmatter_value(content: str, key: str, value: str | None) -> str:
    """Insert/replace/remove one scalar key in the leading YAML frontmatter.

    Line-oriented on purpose: a YAML round-trip would reformat hand-written
    notes (quoting, key order, comments), and these files are edited on the
    desktop too. Everything outside the key's own node is preserved byte for
    byte. `value=None` (or blank) removes the key, and drops the fence entirely
    once it holds nothing else.
    """
    text = " ".join(value.split()) if value else ""
    has_fence = content.startswith("---\n")
    end = content.find("\n---", 4) if has_fence else -1
    if end == -1:
        if not text:
            return content
        return f"---\n{_yaml_line(key, text)}\n---\n\n{content}"

    head_lines = content[4:end].split("\n")
    rest = content[end + 4 :]
    prefix = f"{key}:"
    kept: list[str] = []
    idx = 0
    while idx < len(head_lines):
        # Only a column-0 `key:` is this document's own field; an indented match
        # belongs to some nested mapping and must be left alone.
        if head_lines[idx].startswith(prefix):
            idx = _node_end(head_lines, idx)
            continue
        kept.append(head_lines[idx])
        idx += 1
    if text:
        kept.append(_yaml_line(key, text))
    if not [ln for ln in kept if ln.strip()]:
        # The fence existed only for this key — remove it, and the blank line
        # that separated it from the body, so removal is a clean undo of insert.
        return rest.lstrip("\n")
    return "---\n" + "\n".join(kept) + "\n---" + rest


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
                hits.append(
                    {
                        "path": str(rel),
                        "line": lineno,
                        "text": line.strip(),
                        "category": classify_path(rel),
                    }
                )
                if len(hits) >= max_hits:
                    return hits
    return hits
