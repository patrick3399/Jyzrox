"""Per-work plot outline: convention + structured plot nodes.

Convention (corpus fit 2026-11-05): a work's outline lives at
`<work>/Setting/大綱.md`, where the author keeps it. Setting/ classifies files by
prefix, so the outline is `reference`: listed and searchable, never an entity
note and never main text.

Structure:

    ### 第7章·標題                  ← a plot node (heading, any level 2-4)
    **項目狀態：** …                ← preview text
    *   **第一幕：幕名**             ← a beat inside that node
        *   **劇情節點：** …         ← detail, not a beat (has trailing text)

Nodes carry the chapter number found in their title, which is what lets a plan
be lined up against the chapters that actually exist. Derivation is live from
the file (the file is the source of truth); no derived table is involved.
"""

from __future__ import annotations

import re
from pathlib import Path

from services import novel_fs

_OUTLINE_NAME = "Setting/大綱.md"

_HEADING = re.compile(r"^(#{2,4})\s+(.+?)\s*$")
# A bolded bullet with nothing after it labels a beat; `**劇情節點：** …` (with
# trailing prose) is a detail line inside a beat, not a beat of its own.
_BEAT = re.compile(r"^\s*[*+-]\s+\*\*(.+?)\*\*\s*$")
_CHAPTER_NO = re.compile(r"第(\d+)章")
_MD_NOISE = re.compile(r"[*_`>]|^\s*[*+-]\s+")
_PREVIEW_MAX = 160


def outline_path(work: str) -> str:
    """The outline path for a work (also where the UI says to create one)."""
    return f"{work}/{_OUTLINE_NAME}"


def find_outline(repo_root: str | Path, work: str) -> str | None:
    """Existing outline path for a work, or None."""
    rel = outline_path(work)
    try:
        return rel if novel_fs.file_exists(repo_root, rel) else None
    except novel_fs.NovelPathError:
        return None


def _clean(line: str) -> str:
    return _MD_NOISE.sub("", line).strip()


def parse_outline(content: str) -> list[dict]:
    """Plot nodes of an outline file, in document order.

    Each node is {order, level, title, line, chapter_no, preview, beats}, where
    `beats` are the labelled sub-sections (acts) and `chapter_no` is the chapter
    number named in the title (None when the node is not chapter-scoped).
    """
    _, body = novel_fs.parse_frontmatter(content)
    offset = len(content.splitlines()) - len(body.splitlines())
    nodes: list[dict] = []
    for idx, raw in enumerate(body.splitlines(), 1):
        line_no = idx + offset
        heading = _HEADING.match(raw)
        if heading:
            title = _clean(heading.group(2))
            no = _CHAPTER_NO.search(title)
            nodes.append(
                {
                    "order": len(nodes),
                    "level": len(heading.group(1)),
                    "title": title,
                    "line": line_no,
                    "chapter_no": int(no.group(1)) if no else None,
                    "preview": "",
                    "beats": [],
                }
            )
            continue
        if not nodes:
            continue  # preamble before the first node
        beat = _BEAT.match(raw)
        if beat:
            nodes[-1]["beats"].append({"title": _clean(beat.group(1)), "line": line_no})
        elif not nodes[-1]["preview"]:
            text = _clean(raw)
            if text:
                nodes[-1]["preview"] = text[:_PREVIEW_MAX]
    return nodes


def link_chapters(nodes: list[dict], chapters: list[dict]) -> list[dict]:
    """Attach `chapter_path` to every node whose chapter number exists on disk.

    Matched on the number, not the title, so a node keeps pointing at its
    chapter after a rename. `chapters` arrive in reading order (base chapter
    before its parts), so `01.md` wins over `01-1.md`.
    """
    by_no: dict[int, str] = {}
    for ch in chapters:
        m = re.search(r"\d+", Path(ch["path"]).stem)
        if m:
            by_no.setdefault(int(m.group(0)), ch["path"])
    return [{**n, "chapter_path": by_no.get(n["chapter_no"]) if n["chapter_no"] else None} for n in nodes]
