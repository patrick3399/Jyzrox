"""Novel hub / SSH identity settings router (admin)."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core import audit
from core.auth import require_role
from services import novel_git, novel_remote
from services.novel_gitlock import _enqueue_reindex, _repo, _with_git_lock

logger = logging.getLogger(__name__)
_admin = require_role("admin")


# Separate router: configuring the hub must work BEFORE the module is enabled,
# so the module-enabled gate on `router` must not apply here.

remote_router = APIRouter(tags=["novels-remote"])


class KeyBody(BaseModel):
    regenerate: bool = False


class UrlBody(BaseModel):
    url: str


class TrustBody(BaseModel):
    url: str
    fingerprint: str


class SaveRemoteBody(BaseModel):
    url: str
    confirm_reclone: bool = False


def _parse_target(url: str) -> novel_remote.RemoteTarget:
    try:
        return novel_remote.parse_remote_url(url)
    except novel_remote.InvalidRemote as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@remote_router.get("")
async def remote_get(url: str | None = Query(None), _: dict = Depends(_admin)):
    """`url` is the address being typed in the UI: host trust is judged on it so
    the badge is right before the first save, when no remote is stored yet."""
    repo = _repo()
    stored = await novel_git.get_remote_url(repo)
    trusted = False
    probe = url or stored
    if probe:
        with contextlib.suppress(novel_remote.InvalidRemote):
            trusted = await novel_remote.is_host_trusted(novel_remote.parse_remote_url(probe))
    return {
        "url": stored,
        "repo_exists": (Path(repo) / ".git").exists(),
        "has_key": novel_remote.has_managed_key(),
        "public_key": novel_remote.public_key(),
        "key_fingerprint": await novel_remote.key_fingerprint(),
        "host_trusted": trusted,
    }


@remote_router.post("/key")
async def remote_key(body: KeyBody, auth: dict = Depends(_admin)):
    try:
        pub = await novel_remote.generate_key(overwrite=body.regenerate)
    except novel_remote.KeyExists:
        raise HTTPException(status_code=409, detail={"error": "key_exists"})
    except novel_remote.RemoteToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    await audit.log_audit(auth["user_id"], "novel.remote.key", "regenerated" if body.regenerate else "created")
    return {"public_key": pub, "key_fingerprint": await novel_remote.key_fingerprint()}


@remote_router.post("/hostkeys")
async def remote_hostkeys(body: UrlBody, _: dict = Depends(_admin)):
    target = _parse_target(body.url)
    try:
        keys = await novel_remote.scan_host_keys(target)
    except novel_remote.RemoteToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        "host": target.host,
        "port": target.port,
        "keys": [{"type": k["type"], "fingerprint": k["fingerprint"]} for k in keys],
    }


@remote_router.post("/trust")
async def remote_trust(body: TrustBody, auth: dict = Depends(_admin)):
    target = _parse_target(body.url)
    try:
        await novel_remote.trust_host(target, body.fingerprint)
    except novel_remote.FingerprintMismatch:
        raise HTTPException(status_code=409, detail={"error": "fingerprint_mismatch"})
    except novel_remote.RemoteToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    await audit.log_audit(auth["user_id"], "novel.remote.trust", f"{target.host} {body.fingerprint}")
    return {"ok": True}


@remote_router.post("/test")
async def remote_test(body: UrlBody, _: dict = Depends(_admin)):
    target = _parse_target(body.url)
    probe = await novel_git.ls_remote(target.url)
    return {"ok": probe["ok"], "empty": probe["empty"], "error": probe["error"]}


@remote_router.put("")
async def remote_save(body: SaveRemoteBody, auth: dict = Depends(_admin)):
    target = _parse_target(body.url)

    async def _do():
        repo = _repo()
        try:
            if not (Path(repo) / ".git").exists():
                await novel_git.clone_replace(repo, target.url)
                return {"mode": "cloned"}, True
            relation = await novel_git.history_relation(repo, target.url)
            if relation == "related":
                await novel_git.set_remote_url(repo, target.url)
                await novel_git.fetch(repo)
                return {"mode": "set_url"}, False
            if not body.confirm_reclone:
                st = await novel_git.status(repo)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "history_unrelated",
                        "reason": relation,
                        "unpushed": st["ahead"],
                        "dirty": not st["clean"],
                    },
                )
            await novel_git.clone_replace(repo, target.url)
            return {"mode": "recloned"}, True
        except novel_git.NovelGitError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    result, tree_changed = await _with_git_lock(_do)
    await audit.log_audit(auth["user_id"], "novel.remote.set", f"{result['mode']} {target.url}")
    if tree_changed:
        await _enqueue_reindex()
    return result
