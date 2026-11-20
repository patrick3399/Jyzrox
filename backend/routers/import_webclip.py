"""Web-clip import endpoint."""

import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_role
from core.config import settings
from core.database import get_db
from core.events import EventType, emit_safe
from db.models import Gallery, Image
from services.cas import create_library_symlink, increment_ref_count, store_blob
from services.image_magic import validate_image_magic
from services.media_formats import IMAGE_EXTENSIONS as _SUPPORTED_IMAGE_EXTS

logger = logging.getLogger(__name__)

router = APIRouter()

_member = require_role("member")
_admin = require_role("admin")


_WEB_CLIP_MAX_BYTES = 50 * 1024 * 1024


@router.post("/web-clip", status_code=201)
async def import_web_clip(
    file: UploadFile = File(...),
    source_url: str = Form(..., min_length=1, max_length=4096),
    title: str | None = Form(default=None, max_length=500),
    auth: dict = Depends(_member),
    db: AsyncSession = Depends(get_db),
):
    # The multipart filename is client-controlled and arrives verbatim; keep only
    # its last component so the image row and its library link agree.
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in _SUPPORTED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="Web clip must be a supported image")
    temp = Path(settings.data_training_path) / "web-clips" / f".{uuid.uuid4().hex}{suffix}"
    temp.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with temp.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _WEB_CLIP_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="Web clip is too large")
                digest.update(chunk)
                output.write(chunk)
        if not validate_image_magic(temp):
            raise HTTPException(status_code=400, detail="Web clip is not a valid image")
        sha256 = digest.hexdigest()
        source_id = f"{auth['user_id']}:{sha256}"
        existing = (
            await db.execute(select(Gallery).where(Gallery.source == "webclip", Gallery.source_id == source_id))
        ).scalar_one_or_none()
        if existing is not None:
            return {"status": "exists", "gallery_id": existing.id}
        blob = await store_blob(temp, sha256, db)
        gallery = Gallery(
            source="webclip",
            source_id=source_id,
            source_url=source_url,
            title=(title or "").strip() or Path(filename).stem,
            pages=1,
            download_status="complete",
            import_mode="copy",
            created_by_user_id=auth["user_id"],
            visibility="private",
        )
        db.add(gallery)
        await db.flush()
        image = Image(gallery_id=gallery.id, page_num=1, filename=filename, blob_sha256=sha256)
        db.add(image)
        await increment_ref_count(sha256, db)
        await db.commit()
        await create_library_symlink("webclip", source_id, filename, blob)
        await emit_safe(
            EventType.IMPORT_COMPLETED,
            actor_user_id=auth["user_id"],
            resource_type="gallery",
            resource_id=gallery.id,
            source="webclip",
        )
        return {"status": "imported", "gallery_id": gallery.id}
    finally:
        temp.unlink(missing_ok=True)
