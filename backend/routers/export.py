"""Training Data Export (Kohya format)."""

import asyncio
import json
import os
import re
import zipfile
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.auth import gallery_access_filter, require_role
from core.database import async_session
from db.models import Gallery, Image
from services.cas import resolve_blob_path

_SAFE_ARCNAME = re.compile(r"[^\w.\-]")

# Namespaces that are not trainable concepts and pollute captions
_DEFAULT_EXCLUDED_NAMESPACES = "rating,language,metadata"

# Formats kohya_ss / ai-toolkit / OneTrainer accept as training images
_TRAINABLE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

router = APIRouter(tags=["export"])

_member = require_role("member")


def _caption_tags(
    tags: set[str],
    excluded_namespaces: frozenset[str],
    underscores_to_spaces: bool,
) -> list[str]:
    """Normalize raw 'namespace:name' tag strings into trainer caption tags.

    Strips namespace prefixes, drops excluded namespaces, optionally converts
    booru underscores to spaces, and returns a deterministically sorted list.
    """
    out: set[str] = set()
    for raw in tags:
        ns, sep, name = raw.partition(":")
        if not sep:
            ns, name = "", raw
        if ns in excluded_namespaces:
            continue
        tag = name.strip()
        if not tag:
            continue
        if underscores_to_spaces:
            tag = tag.replace("_", " ")
        out.add(tag)
    return sorted(out)


@router.get("/kohya/{gallery_id}")
async def export_kohya(
    gallery_id: int,
    exclude_namespaces: str = _DEFAULT_EXCLUDED_NAMESPACES,
    underscores_to_spaces: bool = False,
    auth: dict = Depends(_member),
):
    """Generates a zip file containing images and corresponding .txt files with tags."""
    excluded = frozenset(ns.strip() for ns in exclude_namespaces.split(",") if ns.strip())

    async with async_session() as session:
        # Get Gallery with access control
        gallery = (
            await session.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth)))
        ).scalar_one_or_none()
        if not gallery:
            raise HTTPException(status_code=404, detail="Gallery not found")

        gallery_tags = gallery.tags_array or []

        # Get Images with blobs eagerly loaded
        images = (
            (
                await session.execute(
                    select(Image)
                    .where(Image.gallery_id == gallery_id)
                    .order_by(Image.page_num.asc())
                    .options(selectinload(Image.blob))
                )
            )
            .scalars()
            .all()
        )

    if not images:
        raise HTTPException(status_code=404, detail="No images found in gallery")

    # Resolve filesystem paths via CAS
    def _file_path(img):
        if not img.blob:
            return None
        p = resolve_blob_path(img.blob)
        return p if p.exists() else None

    # Check total size before creating ZIP (limit: 2 GB)
    _MAX_ZIP_SIZE = 2 * 1024 * 1024 * 1024
    total_size = sum(img.blob.file_size for img in images if img.blob and img.blob.file_size)
    if total_size > _MAX_ZIP_SIZE:
        raise HTTPException(status_code=413, detail="Gallery too large to export (max 2 GB)")

    # Build the ZIP in a worker thread: the compression loop is fully
    # synchronous and can chew through gigabytes of source data (AIT-002)
    def _build_zip() -> BytesIO:
        zip_buffer = BytesIO()
        excluded_files: list[dict] = []
        used_arcnames: set[str] = set()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for i, img in enumerate(images):
                file_path = _file_path(img)
                if not file_path:
                    continue

                raw_name = img.filename if img.filename else f"image_{i}"

                ext = ((img.blob.extension if img.blob else None) or os.path.splitext(raw_name)[1]).lower()
                if ext not in _TRAINABLE_EXTS:
                    excluded_files.append({"filename": raw_name, "reason": "unsupported_extension"})
                    continue

                basename = _SAFE_ARCNAME.sub("_", os.path.basename(raw_name)) or f"image_{i}"
                page = img.page_num if img.page_num is not None else i + 1
                arcname = f"{page:04d}_{basename}"
                if arcname in used_arcnames:
                    arcname = f"{page:04d}_{i}_{basename}"
                used_arcnames.add(arcname)

                # Add image file to zip
                zip_file.write(str(file_path), arcname=arcname)

                # Combine gallery tags and specific image tags
                all_tags = set(gallery_tags)
                if img.tags_array:
                    all_tags.update(img.tags_array)

                # Create tag text file
                base, _ = os.path.splitext(arcname)
                txt_filename = base + ".txt"
                tag_string = ", ".join(_caption_tags(all_tags, excluded, underscores_to_spaces))

                zip_file.writestr(txt_filename, tag_string)

            if excluded_files:
                zip_file.writestr("manifest.json", json.dumps({"excluded": excluded_files}, indent=2))

        zip_buffer.seek(0)
        return zip_buffer

    zip_buffer = await asyncio.to_thread(_build_zip)

    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=gallery_{gallery_id}_kohya.zip"},
    )
