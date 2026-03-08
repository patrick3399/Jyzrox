"""Gallery import handling (Link and Copy modes)."""

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from core.auth import require_auth
from core.config import settings
from core.redis_client import get_redis

router = APIRouter(tags=["import"])


class ImportRequest(BaseModel):
    source_dir: str
    mode: str = "link"  # "link" or "copy"
    metadata: dict | None = None


@router.post("/")
async def start_import(
    req: ImportRequest,
    request: Request,
    _: dict = Depends(require_auth),
):
    if req.mode not in ("link", "copy"):
        raise HTTPException(status_code=400, detail="Invalid import mode")

    # Use os.path.realpath to resolve symlinks before validating containment.
    # Path.resolve() follows symlinks too, but os.path.realpath is explicit
    # and consistent across Python versions.
    real_source = os.path.realpath(req.source_dir)
    real_allowed = os.path.realpath(settings.data_gallery_path)
    if not real_source.startswith(real_allowed + os.sep) and real_source != real_allowed:
        raise HTTPException(status_code=400, detail="source_dir must be within the gallery path")

    # Create DB entry (raw SQL to avoid PostgreSQL-specific ORM types like ARRAY)
    from sqlalchemy import text

    from core.database import async_session

    title = req.metadata.get("title", "Imported") if req.metadata else "Imported"
    async with async_session() as session:
        result = await session.execute(
            text(
                "INSERT INTO galleries (source, source_id, title, import_mode)"
                " VALUES (:source, :source_id, :title, :mode) RETURNING id"
            ),
            {
                "source": "local",
                "source_id": os.path.basename(req.source_dir),
                "title": title,
                "mode": req.mode,
            },
        )
        gallery_id = result.scalar_one()
        await session.commit()

    arq = request.app.state.arq
    await arq.enqueue_job("local_import_job", req.source_dir, req.mode, gallery_id)
    return {"status": "enqueued", "gallery_id": gallery_id}


@router.get("/progress/{gallery_id}")
async def get_import_progress(
    gallery_id: int,
    _: dict = Depends(require_auth),
):
    """Poll import progress for a gallery."""
    r = get_redis()
    data = await r.get(f"import:progress:{gallery_id}")
    if not data:
        return {"gallery_id": gallery_id, "status": "unknown"}
    return {"gallery_id": gallery_id, **json.loads(data)}
