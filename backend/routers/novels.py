"""Novel module HTTP API (prefix /api/novels).

Read/query endpoints + progress + preferences (this file also holds the write
endpoints; see the WriteBody section below). Git access is via
services.novel_git ONLY, serialized on the Redis lock `novel:git:lock`.

STAB-003: this router may import from services/ and worker/helpers, never the
reverse.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text

import core.queue
from core import audit, events
from core.auth import require_auth, require_role
from core.config import settings
from core.database import async_session
from core.redis_client import get_redis
from db.models import NovelLink, NovelMention, NovelNote
from services import novel_fs, novel_git, novel_index
from worker.helpers import acquire_lock, release_lock

_GIT_LOCK = "novel:git:lock"
logger = logging.getLogger(__name__)


async def _enqueue_reindex() -> None:
    """Refresh the knowledge index after a working-tree mutation.

    Best-effort: the git mutation already succeeded, so a queue outage must not
    fail the request — the daily index cron self-heals. Call this only AFTER
    the git lock is released: novel_index_job takes the same lock and skips
    without retry when it is held.
    """
    try:
        await core.queue.enqueue("novel_index_job", force=True)
    except Exception as exc:
        logger.warning("failed to enqueue novel_index_job after novel mutation: %s", exc)


async def _require_novel_enabled():
    """Raise 404 if the Novel feature is disabled (Redis override, else config default)."""
    val = await get_redis().get("setting:novel_enabled")
    if val is not None:
        enabled = val == b"1"
    else:
        enabled = settings.novel_enabled
    if not enabled:
        raise HTTPException(status_code=404, detail="Novel module is disabled")


router = APIRouter(tags=["novels"], dependencies=[Depends(_require_novel_enabled)])
_member = require_role("member")
_admin = require_role("admin")


def _repo() -> str:
    return settings.novel_repo_path


@router.get("/works")
async def list_works(_: dict = Depends(require_auth)):
    return {"works": novel_fs.list_works(_repo())}


_FILE_CATEGORIES = {"extra", "draft", "reference", "scrap"}


@router.get("/works/{work}/chapters")
async def list_chapters(work: str, _: dict = Depends(require_auth)):
    try:
        return {
            "chapters": novel_fs.list_chapters(_repo(), work),
            "categories": novel_fs.count_work_files(_repo(), work),
        }
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/works/{work}/files")
async def list_work_files_ep(work: str, category: str = Query(...), _: dict = Depends(require_auth)):
    """Non-main canon categories only; main goes through /chapters, setting
    through /notes."""
    if category not in _FILE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"unknown category: {category!r}")
    try:
        return {"files": novel_fs.list_work_files(_repo(), work, category)}
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/file")
async def read_file(path: str = Query(...), _: dict = Depends(require_auth)):
    try:
        content = novel_fs.read_file(_repo(), path)
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "path": path,
        "content": content,
        "base_sha": await novel_git.head_sha(_repo()),
        "acts": novel_fs.parse_acts(content),
        "backlinks": novel_fs.parse_backlinks(content),
    }


@router.get("/search")
async def search(q: str = Query(..., min_length=1), _: dict = Depends(require_auth)):
    return {"hits": novel_fs.keyword_scan(_repo(), q)}


@router.get("/file/history")
async def file_history(path: str = Query(...), _: dict = Depends(require_auth)):
    repo = _repo()
    try:
        novel_fs.safe_repo_path(repo, path)
        return {"commits": await novel_git.log_file(repo, path)}
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except novel_git.NovelGitError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/file/diff")
async def file_diff(
    path: str = Query(...),
    rev: str = Query(...),
    base: str | None = Query(None),
    _: dict = Depends(require_auth),
):
    """Diff of `rev` against its parent, or against `base` when given."""
    repo = _repo()
    try:
        novel_fs.safe_repo_path(repo, path)
        return {"diff": await novel_git.diff_file(repo, path, rev, base=base)}
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except novel_git.NovelGitError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status")
async def repo_status(_: dict = Depends(require_auth)):
    return await novel_git.status(_repo())


class ProgressBody(BaseModel):
    position: str


@router.get("/progress")
async def get_progress(path: str = Query(...), auth: dict = Depends(require_auth)):
    async with async_session() as s:
        row = (
            await s.execute(
                text("SELECT position FROM novel_read_progress WHERE user_id=:u AND file_path=:p"),
                {"u": auth["user_id"], "p": path},
            )
        ).first()
    return {"path": path, "position": row[0] if row else None}


@router.put("/progress")
async def put_progress(body: ProgressBody, path: str = Query(...), auth: dict = Depends(require_auth)):
    async with async_session() as s:
        await s.execute(
            text(
                "INSERT INTO novel_read_progress (user_id, file_path, position, updated_at) "
                "VALUES (:u, :p, :pos, now()) "
                "ON CONFLICT (user_id, file_path) DO UPDATE SET position=:pos, updated_at=now()"
            ),
            {"u": auth["user_id"], "p": path, "pos": body.position},
        )
        await s.commit()
    return {"ok": True}


@router.get("/preferences")
async def get_prefs(auth: dict = Depends(require_auth)):
    async with async_session() as s:
        row = (await s.execute(text("SELECT novel_prefs FROM users WHERE id=:u"), {"u": auth["user_id"]})).first()
    prefs = row[0] if row and row[0] else {}
    # SQLite compat layer stores JSONB as text; normalize to dict.
    if isinstance(prefs, str):
        import json

        prefs = json.loads(prefs) if prefs else {}
    return {"preferences": prefs}


@router.put("/preferences")
async def put_prefs(body: dict, auth: dict = Depends(require_auth)):
    import json

    async with async_session() as s:
        await s.execute(
            text("UPDATE users SET novel_prefs = CAST(:v AS jsonb) WHERE id=:u"),
            {"v": json.dumps(body), "u": auth["user_id"]},
        )
        await s.commit()
    return {"ok": True}


class WriteBody(BaseModel):
    path: str
    content: str
    # Not required for create: a brand-new file has no base revision to be stale
    # against; its only invariant is that the path is free (see file_exists guard).
    base_sha: str = ""
    message: str | None = None
    create: bool = False


async def _with_git_lock(coro_factory):
    """Serialize every repo-mutating git op on the Redis lock `novel:git:lock`."""
    r = get_redis()
    token = await acquire_lock(r, _GIT_LOCK, ttl=60)
    if token is None:
        raise HTTPException(status_code=409, detail="git busy, retry")
    try:
        return await coro_factory()
    finally:
        await release_lock(r, _GIT_LOCK, token)


async def _assert_writable(repo: str, path: str, base_sha: str | None) -> None:
    """Pre-write guard for every mutating endpoint. MUST run under the git lock:
    checking before taking it is a lost-update TOCTOU (a commit could land
    between the check and the write).

    `base_sha=None` means "create": a brand-new file has no base revision to be
    stale against, so its only invariant is that the path is free.
    """
    st = await novel_git.status(repo)
    if st["locked"]:
        raise HTTPException(status_code=409, detail="repo locked; resolve on desktop")
    if base_sha is None:
        if novel_fs.file_exists(repo, path):
            raise HTTPException(status_code=409, detail={"error": "file exists"})
        return
    if st["head"] != base_sha:
        try:
            current = novel_fs.read_file(repo, path)
        except FileNotFoundError:
            current = ""
        raise HTTPException(
            status_code=409,
            detail={"error": "stale base_sha", "current": current, "current_sha": st["head"]},
        )


@router.put("/file")
async def write_file(body: WriteBody, auth: dict = Depends(_member)):
    repo = _repo()
    # Fail fast on an unsafe path before taking the git lock.
    try:
        novel_fs.safe_repo_path(repo, body.path)
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))

    msg = body.message or f"edit: {body.path}"

    async def _do():
        await _assert_writable(repo, body.path, None if body.create else body.base_sha)
        novel_fs.write_file(repo, body.path, body.content)
        return await novel_git.commit_and_push(repo, body.path, msg)

    try:
        result = await _with_git_lock(_do)
    except novel_git.NovelLocked:
        raise HTTPException(status_code=409, detail="conflict; repo locked; resolve on desktop")

    await audit.log_audit(auth["user_id"], "novel.edit", body.path)
    await events.emit_safe(
        events.EventType.NOVEL_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="novel",
        resource_id=body.path,
    )
    await _enqueue_reindex()
    return result


class RevertBody(BaseModel):
    path: str
    rev: str
    base_sha: str
    message: str | None = None


@router.post("/file/revert")
async def revert_file(body: RevertBody, auth: dict = Depends(_member)):
    """Restore one file to its content at `rev` as a NEW commit.

    History is never rewritten: the revert is an ordinary edit whose content
    comes from git instead of the client, so it goes through the same lock,
    staleness guard and commit+push path as PUT /file.
    """
    repo = _repo()
    try:
        novel_fs.safe_repo_path(repo, body.path)
    except novel_fs.NovelPathError as e:
        raise HTTPException(status_code=400, detail=str(e))

    msg = body.message or f"revert: {body.path} to {body.rev[:7]}"

    async def _do():
        await _assert_writable(repo, body.path, body.base_sha)
        content = await novel_git.file_at_rev(repo, body.path, body.rev)
        novel_fs.write_file(repo, body.path, content)
        return await novel_git.commit_and_push(repo, body.path, msg)

    try:
        result = await _with_git_lock(_do)
    except novel_git.NovelLocked:
        raise HTTPException(status_code=409, detail="conflict; repo locked; resolve on desktop")
    except novel_git.NovelGitError as e:
        # Bad rev, or the file did not exist at that revision — caller error.
        raise HTTPException(status_code=400, detail=str(e))

    await audit.log_audit(auth["user_id"], "novel.revert", f"{body.path}@{body.rev}")
    await events.emit_safe(
        events.EventType.NOVEL_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="novel",
        resource_id=body.path,
    )
    await _enqueue_reindex()
    return {**result, "reverted_to": body.rev}


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
        out.append({"path": n.file_path, "title": n.title, "note_type": n.note_type, "frontmatter": fm})
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
