"""SauceNAO reverse image search endpoint."""

import logging
from io import BytesIO

import httpx
from fastapi import APIRouter, Depends, HTTPException
from PIL import Image as PILImage
from pydantic import BaseModel
from sqlalchemy import select

from core.auth import require_auth
from core.database import async_session
from db.models import Blob, Image
from services.cas import resolve_blob_path
from services.credential import get_credential
from services.saucenao import RateLimitError, SauceNaoError, search_by_image

logger = logging.getLogger(__name__)
router = APIRouter(tags=["saucenao"])

_MAX_UPLOAD_SIZE = 15 * 1024 * 1024  # SauceNAO file size limit


class SearchRequest(BaseModel):
    image_id: int


@router.post("/search")
async def saucenao_search(body: SearchRequest, _: dict = Depends(require_auth)):
    """Search SauceNAO for the source of an image."""
    api_key = await get_credential("saucenao")
    if not api_key:
        raise HTTPException(status_code=400, detail="saucenao_not_configured")

    async with async_session() as session:
        result = await session.execute(
            select(Image, Blob)
            .join(Blob, Image.blob_sha256 == Blob.sha256)
            .where(Image.id == body.image_id)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Image not found")
        _, blob = row.tuple()

    path = resolve_blob_path(blob)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on disk")

    # Only resize if file exceeds SauceNAO's upload limit
    if path.stat().st_size > _MAX_UPLOAD_SIZE:
        with PILImage.open(path) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.thumbnail((2000, 2000))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            image_bytes = buf.getvalue()
    else:
        image_bytes = path.read_bytes()

    try:
        results = await search_by_image(
            image_bytes,
            api_key,
            filename=f"{blob.sha256}{blob.extension}",
        )
    except RateLimitError:
        raise HTTPException(status_code=429, detail="rate_limit")
    except SauceNaoError as exc:
        logger.warning("SauceNAO error: %s", exc)
        raise HTTPException(status_code=502, detail="saucenao_error")
    except httpx.HTTPError as exc:
        logger.warning("SauceNAO request failed: %s", exc)
        raise HTTPException(status_code=502, detail="saucenao_error")

    return {"results": results}
