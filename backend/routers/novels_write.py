"""Novel write endpoints (save, revert, summary)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import audit, events
from core.auth import require_role
from services import novel_fs, novel_git
from services.novel_gitlock import _assert_writable, _enqueue_reindex, _repo, _with_git_lock

logger = logging.getLogger(__name__)
router = APIRouter()
_member = require_role("member")
_admin = require_role("admin")


class WriteBody(BaseModel):
    path: str
    content: str
    # Not required for create: a brand-new file has no base revision to be stale
    # against; its only invariant is that the path is free (see file_exists guard).
    base_sha: str = ""
    message: str | None = None
    create: bool = False


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


class SummaryBody(BaseModel):
    path: str
    summary: str
    base_sha: str


@router.put("/file/summary")
async def put_summary(body: SummaryBody, auth: dict = Depends(_member)):
    """Set (or clear, with an empty string) a chapter's `summary:` frontmatter.

    The summary is authored content, so it lives in the file — the DB stays
    derived-only (spec §2). Writing goes through the same guard/commit path as
    any other edit; only the key's own line changes.
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
        updated = novel_fs.set_frontmatter_value(current, "summary", body.summary)
        novel_fs.write_file(repo, body.path, updated)
        return await novel_git.commit_and_push(repo, body.path, f"summary: {body.path}")

    try:
        result = await _with_git_lock(_do)
    except novel_git.NovelLocked:
        raise HTTPException(status_code=409, detail="conflict; repo locked; resolve on desktop")

    await audit.log_audit(auth["user_id"], "novel.summary", body.path)
    await events.emit_safe(
        events.EventType.NOVEL_UPDATED,
        actor_user_id=auth["user_id"],
        resource_type="novel",
        resource_id=body.path,
    )
    await _enqueue_reindex()
    return result
