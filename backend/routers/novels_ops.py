"""Novel outline, lint, fix, sync, graph, notes and reindex endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from core import audit, events
from core.auth import require_auth, require_role
from core.database import async_session
from db.models import NovelLink, NovelMention, NovelNote
from services import novel_format, novel_fs, novel_git, novel_index, novel_outline
from services.novel_gitlock import _assert_writable, _enqueue_reindex, _repo, _with_git_lock

logger = logging.getLogger(__name__)
router = APIRouter()
_member = require_role("member")
_admin = require_role("admin")


@router.get("/works/{work}/outline")
async def work_outline(work: str, _: dict = Depends(require_auth)):
    """A work's plot nodes, each lined up with the chapter it plans (if written).

    Derived live from `參考/大綱.md` — the file is the source of truth and a
    single small read, so there is no derived table to go stale. `path` is null
    when the work has no outline yet, and `canonical_path` is where one goes.
    """
    repo = _repo()
    try:
        chapters = novel_fs.list_chapters(repo, work)
        path = novel_outline.find_outline(repo, work)
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if path is None:
        return {"path": None, "canonical_path": novel_outline.outline_path(work), "nodes": []}
    nodes = novel_outline.parse_outline(novel_fs.read_file(repo, path))
    return {
        "path": path,
        "canonical_path": novel_outline.outline_path(work),
        "nodes": novel_outline.link_chapters(nodes, chapters),
    }


# ── FORMAT.md lint / fix (Phase 1.7) ───────────────────────────────────────


def _lint_file(repo: str, path: str) -> list[dict]:
    return novel_format.check_text(novel_fs.read_file(repo, path), category=novel_fs.classify_path(path))


@router.get("/file/lint")
async def lint_file(path: str = Query(...), _: dict = Depends(require_auth)):
    repo = _repo()
    try:
        issues = await asyncio.to_thread(_lint_file, repo, path)
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="not found")
    return {"path": path, "issues": issues}


def _lint_work_sync(repo: str, work: str) -> list[dict]:
    """Lint every main chapter, reading each file exactly once.

    Enumerating with ``main_chapter_paths`` instead of ``list_chapters``: the
    latter reads each file to compute character counts and summaries, which the
    lint does not need, so going through it read the whole work twice.
    """
    return [{"path": path, "issues": _lint_file(repo, path)} for path in novel_fs.main_chapter_paths(repo, work)]


@router.get("/works/{work}/lint")
async def lint_work(work: str, _: dict = Depends(require_auth)):
    """Every main chapter of one work, mirroring the desktop batch scan."""
    repo = _repo()
    try:
        # Whole-work read: off the event loop so one batch lint cannot stall
        # every other request for its duration.
        files = await asyncio.to_thread(_lint_work_sync, repo, work)
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"files": files, "total": sum(len(f["issues"]) for f in files)}


class FixBody(BaseModel):
    path: str
    base_sha: str


@router.post("/file/fix")
async def fix_file(body: FixBody, auth: dict = Depends(_member)):
    """Apply the auto-fixable FORMAT.md rules and commit if anything changed.

    Nothing to fix → no commit, `changes: []`. The un-fixable rules (a missing
    chapter-end marker) stay in the lint output for the author to resolve.
    """
    repo = _repo()
    try:
        novel_fs.safe_repo_path(repo, body.path)
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async def _do():
        await _assert_writable(repo, body.path, body.base_sha)
        try:
            current = novel_fs.read_file(repo, body.path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="not found")
        fixed, changes = novel_format.fix_text(current)
        if not changes:
            return {"changes": [], "head": body.base_sha, "pushed": False}
        novel_fs.write_file(repo, body.path, fixed)
        result = await novel_git.commit_and_push(repo, body.path, f"format: {body.path}")
        return {**result, "changes": changes}

    try:
        result = await _with_git_lock(_do)
    except novel_git.NovelLocked:
        raise HTTPException(status_code=409, detail="conflict; repo locked; resolve on desktop")

    if result["changes"]:
        await audit.log_audit(auth["user_id"], "novel.format", body.path)
        await events.emit_safe(
            events.EventType.NOVEL_UPDATED,
            actor_user_id=auth["user_id"],
            resource_type="novel",
            resource_id=body.path,
        )
        await _enqueue_reindex()
    return result


@router.post("/sync")
async def sync(_: dict = Depends(_member)):
    async def _do():
        repo = _repo()
        await novel_git.fetch(repo)
        # pull_ff exits 0 even when already up to date, so "new commits landed"
        # must be read from behind>0 (post-fetch), not from pull_ff's result.
        behind = (await novel_git.status(repo))["behind"] > 0
        pulled = await novel_git.pull_ff(repo)
        return {"pulled": pulled}, behind and pulled

    result, tree_changed = await _with_git_lock(_do)
    if tree_changed:
        await _enqueue_reindex()
    return result


@router.post("/reset")
async def reset(auth: dict = Depends(_admin)):
    async def _do():
        await novel_git.reset_to_origin(_repo())
        return {"ok": True}

    result = await _with_git_lock(_do)
    await audit.log_audit(auth["user_id"], "novel.reset", _repo())
    await _enqueue_reindex()
    return result


# ── Knowledge index (Phase 1 Track A) ──────────────────────────────────────


def _story_order(fm: dict) -> float:
    """Sort key for the plot timeline; notes without story_order sink to the end."""
    raw = fm.get("story_order")
    if raw is None:
        return float("inf")
    try:
        return float(raw)
    except TypeError, ValueError:
        return float("inf")


@router.get("/graph")
async def graph(_: dict = Depends(require_auth)):
    """Nodes (notes + ALL chapters) and edges (mention + resolved wikilinks).

    Chapters are enumerated from the live tree so 0-mention chapters appear
    too (spec §4.6 #7); mention-derived paths are unioned in so index rows
    for files that moved since the last reindex keep their edges anchored.
    """
    async with async_session() as s:
        notes = (await s.execute(select(NovelNote))).scalars().all()
        mentions = (await s.execute(select(NovelMention))).scalars().all()
        links = (await s.execute(select(NovelLink))).scalars().all()
    nodes = [{"id": n.file_path, "label": n.title, "type": "note"} for n in notes]
    repo = _repo()
    try:
        fs_chapters = {ch["path"] for w in novel_fs.list_works(repo) for ch in novel_fs.list_chapters(repo, w["name"])}
    except OSError as exc:
        # Repo unreadable must not take the whole graph down — degrade to the
        # pre-Phase-1.6 mention-derived chapter set.
        logger.warning("graph: chapter scan failed, falling back to mention-derived: %s", exc)
        fs_chapters = set()
    chapters = sorted(fs_chapters | {m.chapter_path for m in mentions})
    nodes += [{"id": c, "label": c.split("/")[-1], "type": "chapter"} for c in chapters]
    edges = [{"src": m.note_path, "dst": m.chapter_path, "kind": "mention"} for m in mentions]
    edges += [{"src": link.src_path, "dst": link.dst_path, "kind": "link"} for link in links if link.dst_path]
    return {"nodes": nodes, "edges": edges}


@router.get("/notes")
async def list_notes_ep(
    type: str | None = Query(None),
    tag: str | None = Query(None),
    sort: str | None = Query(None),
    _: dict = Depends(require_auth),
):
    async with async_session() as s:
        rows = (await s.execute(select(NovelNote))).scalars().all()
    out = []
    for n in rows:
        fm = n.frontmatter or {}
        if type and n.note_type != type:
            continue
        if tag and tag not in (fm.get("tags") or []):
            continue
        out.append(
            {
                "path": n.file_path,
                "title": n.title,
                "note_type": n.note_type,
                "aliases": list(n.aliases or []),
                "frontmatter": fm,
            }
        )
    if sort == "story_order":
        out.sort(key=lambda x: _story_order(x["frontmatter"]))
    return {"notes": out}


@router.get("/notes/appearances")
async def appearances(path: str = Query(...), _: dict = Depends(require_auth)):
    """A note's mentions across chapters, chapter-ordered (character appearance order)."""
    async with async_session() as s:
        rows = (
            (
                await s.execute(
                    select(NovelMention).where(NovelMention.note_path == path).order_by(NovelMention.chapter_path)
                )
            )
            .scalars()
            .all()
        )
    return {
        "appearances": [
            {"chapter_path": r.chapter_path, "mention_count": r.mention_count, "first_offset": r.first_offset}
            for r in rows
        ]
    }


@router.post("/reindex")
async def reindex(auth: dict = Depends(_admin)):
    """Rebuild the knowledge index now (admin). Serialized on the git lock so it
    never reads the tree mid-mutation."""

    async def _do():
        async with async_session() as s:
            stats = await novel_index.reindex_all(s, _repo())
            await s.commit()
        return stats

    stats = await _with_git_lock(_do)
    await audit.log_audit(auth["user_id"], "novel.reindex", _repo())
    return {"stats": stats}


# ── Hub / SSH identity settings (admin) ────────────────────────────────────
# Separate router: configuring the hub must work BEFORE the module is enabled,
# so the module-enabled gate on `router` must not apply here.
