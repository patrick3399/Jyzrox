"""Pure derivation of the novel knowledge index (notes / links / mentions).

Task 2 covers the pure builders (no DB, no git — repo root in, plain records
out) so parsing stays unit-testable. Task 4 adds async persistence in this same
module. STAB-003: importable by routers and workers; never imports routers.

Adapted per spec §4.5.8: mention-scan is the primary edge source (the corpus has
0 wikilinks today); entity names come from Setting/ note titles + optional
`aliases` frontmatter, tolerant of notes with no structured metadata.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import NovelLink, NovelMention, NovelNote
from services import novel_fs


def note_aliases(frontmatter: dict, title: str) -> list[str]:
    """Distinct names to scan bodies for: the title plus any `aliases` list."""
    names: list[str] = [title]
    raw = frontmatter.get("aliases") or []
    if isinstance(raw, list):
        names.extend(str(a).strip() for a in raw if str(a).strip())
    seen: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.append(n)
    return seen


def build_note_records(repo_root: str | Path) -> list[dict]:
    recs: list[dict] = []
    for note in novel_fs.list_notes(repo_root):
        text = novel_fs.read_file(repo_root, note["path"])
        fm, _ = novel_fs.parse_frontmatter(text)
        recs.append(
            {
                "file_path": note["path"],
                "title": note["title"],
                "note_type": fm.get("type"),
                "aliases": note_aliases(fm, note["title"]),
                "frontmatter": fm,
            }
        )
    return recs


def _title_to_path(repo_root: str | Path) -> dict[str, str]:
    return {n["title"]: n["path"] for n in novel_fs.list_notes(repo_root)}


def build_link_records(repo_root: str | Path) -> list[dict]:
    """`[[wikilink]]` edges across all `.md`; dst_path=None marks a broken link."""
    root = Path(repo_root).resolve()
    title_map = _title_to_path(repo_root)
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root)
        if any(p.startswith(".") for p in rel.parts):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:  # noqa: S112 — unreadable/binary file, skip silently
            continue
        for dst in novel_fs.parse_backlinks(text):
            key = (str(rel), dst)
            if key in seen:
                continue
            seen.add(key)
            out.append({"src_path": str(rel), "dst_title": dst, "dst_path": title_map.get(dst)})
    return out


def _chapter_paths(repo_root: str | Path) -> list[str]:
    paths: list[str] = []
    for w in novel_fs.list_works(repo_root):
        paths.extend(c["path"] for c in novel_fs.list_chapters(repo_root, w["name"]))
    return sorted(paths)


def scan_mentions(repo_root: str | Path) -> list[dict]:
    """Body-text scan: count each entity name/alias per chapter, record first offset.

    One alternation regex over each chapter (corpus ~8 MB; YAGNI on Aho-Corasick).
    Longest aliases first so overlapping names prefer the longer match.
    """
    notes = build_note_records(repo_root)
    alias_to_note: dict[str, str] = {}
    for n in notes:
        for a in n["aliases"]:
            alias_to_note.setdefault(a, n["file_path"])
    if not alias_to_note:
        return []
    aliases = sorted(alias_to_note, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(a) for a in aliases))
    out: list[dict] = []
    for ch in _chapter_paths(repo_root):
        text = novel_fs.read_file(repo_root, ch)
        counts: dict[str, int] = {}
        first: dict[str, int] = {}
        for m in pattern.finditer(text):
            note_path = alias_to_note[m.group(0)]
            counts[note_path] = counts.get(note_path, 0) + 1
            if note_path not in first:
                first[note_path] = m.start()
        for note_path, cnt in counts.items():
            out.append(
                {
                    "note_path": note_path,
                    "chapter_path": ch,
                    "mention_count": cnt,
                    "first_offset": first[note_path],
                }
            )
    return out


async def reindex_all(session: AsyncSession, repo_root: str | Path) -> dict:
    """Full rebuild of the three derived tables from the working tree.

    Delete-then-insert; deterministic (re-running yields identical rows). The
    ORM column variants bind Python list/dict natively on both PG and SQLite.
    Caller commits.
    """
    notes = build_note_records(repo_root)
    links = build_link_records(repo_root)
    mentions = scan_mentions(repo_root)

    await session.execute(delete(NovelMention))
    await session.execute(delete(NovelLink))
    await session.execute(delete(NovelNote))

    for n in notes:
        session.add(
            NovelNote(
                file_path=n["file_path"],
                title=n["title"],
                note_type=n["note_type"],
                aliases=n["aliases"],
                frontmatter=n["frontmatter"],
            )
        )
    for link in links:
        session.add(NovelLink(src_path=link["src_path"], dst_title=link["dst_title"], dst_path=link["dst_path"]))
    for m in mentions:
        session.add(
            NovelMention(
                note_path=m["note_path"],
                chapter_path=m["chapter_path"],
                mention_count=m["mention_count"],
                first_offset=m["first_offset"],
            )
        )
    await session.flush()
    return {"notes": len(notes), "links": len(links), "mentions": len(mentions)}
