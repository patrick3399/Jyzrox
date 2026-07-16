"""SauceNAO reverse image search endpoint."""

import logging
from io import BytesIO

import httpx
from fastapi import APIRouter, Depends, HTTPException
from PIL import Image as PILImage
from pydantic import BaseModel
from sqlalchemy import select

from core.auth import gallery_access_filter, require_role
from core.database import async_session
from db.models import Blob, Gallery, Image
from services.cas import resolve_blob_path
from services.credential import get_credential
from services.saucenao import RateLimitError, SauceNaoError, search_by_image

logger = logging.getLogger(__name__)
router = APIRouter(tags=["saucenao"])

_MAX_UPLOAD_SIZE = 15 * 1024 * 1024  # SauceNAO file size limit


class SearchRequest(BaseModel):
    image_id: int


class BatchSearchRequest(BaseModel):
    image_ids: list[int]
    auto_fill_source: bool = True
    min_similarity: float = 80.0


def _image_bytes(blob: Blob) -> bytes:
    path = resolve_blob_path(blob)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file not found on disk")
    if path.stat().st_size <= _MAX_UPLOAD_SIZE:
        return path.read_bytes()
    with PILImage.open(path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((2000, 2000))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


async def _load_image(image_id: int, auth: dict) -> tuple[Image, Blob, Gallery]:
    async with async_session() as session:
        row = (
            await session.execute(
                select(Image, Blob, Gallery)
                .join(Blob, Image.blob_sha256 == Blob.sha256)
                .join(Gallery, Gallery.id == Image.gallery_id)
                .where(Image.id == image_id, gallery_access_filter(auth))
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Image not found")
        return row.tuple()


@router.post("/search")
async def saucenao_search(body: SearchRequest, auth: dict = Depends(require_role("member"))):
    """Search SauceNAO for the source of an image."""
    api_key = await get_credential("saucenao")
    if not api_key:
        raise HTTPException(status_code=400, detail="saucenao_not_configured")

    _, blob, _ = await _load_image(body.image_id, auth)
    image_bytes = _image_bytes(blob)

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


@router.post("/batch")
async def saucenao_batch(body: BatchSearchRequest, auth: dict = Depends(require_role("member"))):
    image_ids = list(dict.fromkeys(body.image_ids))
    if not image_ids or len(image_ids) > 6:
        raise HTTPException(status_code=400, detail="Batch must contain 1 to 6 unique image IDs")
    if not 0 <= body.min_similarity <= 100:
        raise HTTPException(status_code=400, detail="min_similarity must be between 0 and 100")
    api_key = await get_credential("saucenao")
    if not api_key:
        raise HTTPException(status_code=400, detail="saucenao_not_configured")
    output = []
    for image_id in image_ids:
        try:
            image, blob, gallery = await _load_image(image_id, auth)
            results = await search_by_image(_image_bytes(blob), api_key, filename=f"{blob.sha256}{blob.extension}")
            best = results[0] if results else None
            applied = False
            if body.auto_fill_source and best and best["source_url"] and best["similarity"] >= body.min_similarity:
                async with async_session() as session:
                    writable = (
                        await session.execute(
                            select(Gallery).where(Gallery.id == gallery.id, gallery_access_filter(auth))
                        )
                    ).scalar_one_or_none()
                    if writable is not None and (
                        auth["role"] == "admin" or writable.created_by_user_id in (None, auth["user_id"])
                    ):
                        writable.source_url = best["source_url"]
                        await session.commit()
                        applied = True
            output.append({"image_id": image.id, "gallery_id": gallery.id, "best": best, "source_applied": applied})
        except (HTTPException, SauceNaoError, httpx.HTTPError) as exc:
            output.append({"image_id": image_id, "error": str(exc)})
    return {"results": output}
