"""Pure derivation of the novel knowledge index (notes / links / mentions).

Pure builders (repo root in, plain records out) plus async persistence.
STAB-003: importable by routers and workers; never imports routers.

Entity model (corpus fit 2026-11-05): an entity is a `設定-<name>v<N>.md` note;
the highest version of a name within a work is the canonical one and the only
one that collects mentions. `setting*.md` world documents are scanned only for
explicit `aliases:` frontmatter. Mentions never cross works.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import NovelLink, NovelMention, NovelNote
from services import novel_format, novel_fs

# `設定-<name>` with an optional trailing `v<N>` version.
_SETTING_STEM = re.compile(r"^設定-(?P<name>.+?)(?:v(?P<ver>\d+))?$")


def entity_of(stem: str) -> tuple[str, int] | None:
    """(entity name, version) of a `設定-` note stem; None for anything else."""
    m = _SETTING_STEM.match(stem)
    if not m:
        return None
    return m["name"], int(m["ver"] or 0)


def _dedupe(names: list[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def _frontmatter_aliases(fm: dict) -> list[str]:
    raw = fm.get("aliases") or []
    if not isinstance(raw, list):
        return []
    return [str(a).strip() for a in raw if str(a).strip()]


def build_note_records(repo_root: str | Path) -> list[dict]:
    notes = novel_fs.list_notes(repo_root)
    # Highest version per (work, entity name) is canonical.
    best: dict[tuple[str, str], tuple[int, str]] = {}
    for note in notes:
        ent = entity_of(Path(note["path"]).stem)
        if ent is None:
            continue
        key = (note["work"], ent[0])
        if key not in best or ent[1] > best[key][0]:
            best[key] = (ent[1], note["path"])
    canonical = {path for _, path in best.values()}

    recs: list[dict] = []
    for note in notes:
        text = novel_fs.read_file(repo_root, note["path"])
        fm, _ = novel_fs.parse_frontmatter(text)
        ent = entity_of(Path(note["path"]).stem)
        if note["path"] in canonical:
            aliases = _dedupe([ent[0], *_frontmatter_aliases(fm)]) if ent else []
        elif ent is None:
            aliases = _dedupe(_frontmatter_aliases(fm))  # world doc: opt-in only
        else:
            aliases = []  # superseded version of an entity
        recs.append(
            {
                "file_path": note["path"],
                "work": note["work"],
                "title": note["title"],
                "note_type": fm.get("type"),
                "aliases": aliases,
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


def scan_mentions(repo_root: str | Path) -> list[dict]:
    """Body-text scan of main chapters, per work: count each entity's names per
    chapter and record the first offset.

    One alternation regex per work (corpus ~2 MB of markdown). Longest aliases
    first so overlapping names prefer the longer match.
    """
    by_work: dict[str, dict[str, str]] = {}
    for n in build_note_records(repo_root):
        for a in n["aliases"]:
            by_work.setdefault(n["work"], {}).setdefault(a, n["file_path"])
    out: list[dict] = []
    for w in novel_fs.list_works(repo_root):
        alias_to_note = by_work.get(w["name"])
        if not alias_to_note:
            continue
        aliases = sorted(alias_to_note, key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(a) for a in aliases))
        for ch in novel_fs.list_chapters(repo_root, w["name"]):
            text = novel_fs.read_file(repo_root, ch["path"])
            counts: dict[str, int] = {}
            first: dict[str, int] = {}
            for m in pattern.finditer(text):
                note_path = alias_to_note[m.group(0)]
                counts[note_path] = counts.get(note_path, 0) + 1
                first.setdefault(note_path, m.start())
            for note_path, cnt in counts.items():
                out.append(
                    {
                        "note_path": note_path,
                        "chapter_path": ch["path"],
                        "mention_count": cnt,
                        "first_offset": first[note_path],
                    }
                )
    return out


def corpus_health(repo_root: str | Path, notes: list[dict], mentions: list[dict]) -> dict:
    """Drift signals for the operator: files the conventions do not place,
    chapters failing FORMAT.md, entities nothing mentions."""
    root = Path(repo_root).resolve()
    stray: list[str] = []
    issues = 0
    for w in novel_fs.list_works(root):
        for f in sorted((root / w["name"]).glob("*.md")):
            rel = f.relative_to(root)
            if novel_fs.classify_path(rel) == "reference" and f.name.lower() != "format.md":
                stray.append(str(rel))
        for path in novel_fs.main_chapter_paths(root, w["name"]):
            if novel_format.check_text(novel_fs.read_file(root, path)):
                issues += 1
    mentioned = {m["note_path"] for m in mentions}
    silent = [n["file_path"] for n in notes if n["aliases"] and n["file_path"] not in mentioned]
    return {"stray_root_files": stray, "chapters_with_format_issues": issues, "entities_without_mentions": silent}


async def reindex_all(session: AsyncSession, repo_root: str | Path) -> dict:
    """Full rebuild of the three derived tables from the working tree.

    Delete-then-insert; deterministic (re-running yields identical rows). The
    ORM column variants bind Python list/dict natively on both PG and SQLite.
    Caller commits.
    """
    notes = build_note_records(repo_root)
    links = build_link_records(repo_root)
    mentions = scan_mentions(repo_root)
    health = corpus_health(repo_root, notes, mentions)

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
    return {"notes": len(notes), "links": len(links), "mentions": len(mentions), "health": health}
