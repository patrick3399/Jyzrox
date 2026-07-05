"""Novel module HTTP API (prefix /api/novels).

Read/query endpoints + progress + preferences (this file also holds the write
endpoints; see the WriteBody section below). Git access is via
services.novel_git ONLY, serialized on the Redis lock `novel:git:lock`.

STAB-003: this router may import from services/ and worker/helpers, never the
reverse.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from core.auth import require_auth, require_role
from core.config import settings
from core.database import async_session
from services import novel_fs, novel_git

router = APIRouter(tags=["novels"])
_member = require_role("member")
_admin = require_role("admin")


def _repo() -> str:
    return settings.novel_repo_path


@router.get("/works")
async def list_works(_: dict = Depends(require_auth)):
    return {"works": novel_fs.list_works(_repo())}


@router.get("/works/{work}/chapters")
async def list_chapters(work: str, _: dict = Depends(require_auth)):
    try:
        return {"chapters": novel_fs.list_chapters(_repo(), work)}
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
    return {"commits": await novel_git.log_file(_repo(), path)}


@router.get("/file/diff")
async def file_diff(path: str = Query(...), rev: str = Query(...), _: dict = Depends(require_auth)):
    return {"diff": await novel_git.diff_file(_repo(), path, rev)}


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
