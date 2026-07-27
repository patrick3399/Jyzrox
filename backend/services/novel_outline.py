"""Per-work plot outline: convention + structured plot nodes.

Convention (Phase 1.7): a work's outline lives at `<work>/參考/大綱.md`
(`outline.md` also accepted). It sits under `參考/` deliberately — that folder
already classifies as `reference`, so the file is listed, searchable and synced
with no new category plumbing, and a work-root `大綱.md` would instead be
classified as main text and pollute the chapter list.

Structure, following the shape the corpus already uses:

    ### 第7章：星核的救贖          ← a plot node (heading, any level 2-4)
    **項目狀態：** …                ← preview text
    *   **第一幕：命運的劫獄**       ← a beat inside that node
        *   **劇情節點：** …         ← detail, not a beat (has trailing text)

Nodes carry the chapter number found in their title, which is what lets a plan
be lined up against the chapters that actually exist. Derivation is live from
the file (the file is the source of truth); parsing a work's outline is a single
small read, so no derived table is involved.
"""

from __future__ import annotations

import re
from pathlib import Path

from services import novel_fs

# Outline file names accepted inside a work's 參考/ folder.
_OUTLINE_NAMES = ("大綱.md", "outline.md", "Outline.md")
_REFERENCE_DIR = "參考"

_HEADING = re.compile(r"^(#{2,4})\s+(.+?)\s*$")
# A bolded bullet with nothing after it labels a beat; `**劇情節點：** …` (with
# trailing prose) is a detail line inside a beat, not a beat of its own.
_BEAT = re.compile(r"^\s*[*+-]\s+\*\*(.+?)\*\*\s*$")
_CHAPTER_NO = re.compile(r"第(\d+)章")
# Fallback shape: a heading-less outline that lists chapters as bolded bullets
# with their synopsis inline (`*   **第1章（受肉儀式）：** …`), which is how the
# outline already in the corpus is written.
_BULLET_NODE = re.compile(r"^\s*[*+-]\s+\*\*(.+?)\*\*\s*[：:]?\s*(.*)$")
_MD_NOISE = re.compile(r"[*_`>]|^\s*[*+-]\s+")
_PREVIEW_MAX = 160


def outline_path(work: str) -> str:
    """The canonical outline path for a work (used when creating one)."""
    return f"{work}/{_REFERENCE_DIR}/{_OUTLINE_NAMES[0]}"


def find_outline(repo_root: str | Path, work: str) -> str | None:
    """Existing outline path for a work, or None. Accepts the alternate names."""
    for name in _OUTLINE_NAMES:
        rel = f"{work}/{_REFERENCE_DIR}/{name}"
        try:
            if novel_fs.file_exists(repo_root, rel):
                return rel
        except novel_fs.NovelPathError:
            return None
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
    return nodes or _parse_bullet_outline(body, offset)


def _parse_bullet_outline(body: str, offset: int) -> list[dict]:
    """Chapter-per-bullet outlines (no headings at all) — see _BULLET_NODE."""
    nodes: list[dict] = []
    for idx, raw in enumerate(body.splitlines(), 1):
        m = _BULLET_NODE.match(raw)
        if not m:
            continue
        label = _clean(m.group(1))
        no = _CHAPTER_NO.search(label)
        if not no:
            continue
        nodes.append(
            {
                "order": len(nodes),
                "level": 3,
                "title": label.rstrip("：:"),
                "line": idx + offset,
                "chapter_no": int(no.group(1)),
                "preview": _clean(m.group(2))[:_PREVIEW_MAX],
                "beats": [],
            }
        )
    return nodes


def _chapter_no_of(stem: str) -> int | None:
    m = re.search(r"\d+", stem)
    return int(m.group(0)) if m else None


def link_chapters(nodes: list[dict], chapters: list[dict]) -> list[dict]:
    """Attach `chapter_path` to every node whose chapter number exists on disk.

    The corpus names chapters `01.md`, `02.md`, … so the match is on the number,
    not the title: an outline node keeps pointing at its chapter after a rename.
    Nodes with no chapter yet are the still-unwritten part of the plan.
    """
    by_no: dict[int, str] = {}
    for ch in chapters:
        no = _chapter_no_of(Path(ch["path"]).stem)
        if no is not None:
            by_no.setdefault(no, ch["path"])
    return [{**n, "chapter_path": by_no.get(n["chapter_no"]) if n["chapter_no"] else None} for n in nodes]
